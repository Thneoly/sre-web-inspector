from __future__ import annotations

import asyncio

from sre_web_inspector import BrowserContextManager
from sre_web_inspector.inspector import WebInspectionNode
from sre_web_inspector.network.factory import (
    build_context_middleware_manager,
    build_page_middleware_manager,
)


CONFIG = {
    "context_middlewares": {
        "routes": [
            {
                "name": "block_images",
                "pattern": "**/*",
                "middlewares": [
                    {"type": "block_resource", "resource_types": ["image", "font"]}
                ],
            }
        ]
    },
    "network_middlewares": {
        "responses": [
            {
                "type": "json_response_saver",
                "output_dir": "outputs/responses/global",
                "url_keywords": ["/api/"],
            }
        ]
    },
}


async def main() -> None:
    async with BrowserContextManager(headless=False, slow_mo=300) as cm:
        if cm.context is None:
            raise RuntimeError("Browser context is not initialized")

        await build_context_middleware_manager(CONFIG).bind_to_context(cm.context)

        inspector = WebInspectionNode(cm)

        page_cfg = {
            "name": "pod_resource",
            "url": "https://example.com/pods",
            "network_middlewares": {
                "routes": [
                    {
                        "name": "pod_api_patch",
                        "pattern": "**/*/api/pods*",
                        "middlewares": [
                            {"type": "query_param_patch", "set": {"pageSize": 200}},
                            {"type": "route_recorder", "output_dir": "outputs/network/pod_resource"},
                        ],
                    }
                ]
            },
        }

        page = await cm.new_page()
        await build_page_middleware_manager(CONFIG, page_cfg).bind_to_page(page)

        try:
            result = await inspector.inspect_page(page_cfg["url"], page=page, name=page_cfg["name"])
            print(result)
        finally:
            await page.close()


if __name__ == "__main__":
    asyncio.run(main())
