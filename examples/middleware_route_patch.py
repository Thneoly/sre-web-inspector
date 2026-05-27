import asyncio

from sre_web_inspector import BrowserContextManager
from sre_web_inspector.network import NetworkMiddlewareManager
from sre_web_inspector.network.middlewares import (
    QueryParamPatchMiddleware,
    HeaderPatchMiddleware,
    RouteRecorderMiddleware,
    JsonResponseSaverMiddleware,
)


async def main():
    async with BrowserContextManager(user_data_dir="./user-data", headless=False) as cm:
        page = cm.page

        network = NetworkMiddlewareManager()
        network.routes.add_route(
            "**/*/api/pods*",
            [
                QueryParamPatchMiddleware(set_params={"pageSize": 200}, remove_params=["page"]),
                HeaderPatchMiddleware(set_headers={"X-SRE-Inspector": "true"}),
                RouteRecorderMiddleware(output_dir="outputs/network"),
            ],
        )
        network.responses.add(
            JsonResponseSaverMiddleware(output_dir="outputs/responses", url_keywords=["/api/pods"])
        )

        await network.bind(page)
        await cm.goto("https://internal.example.com/pods")
        await cm.screenshot("outputs/screenshots/pods.png")


if __name__ == "__main__":
    asyncio.run(main())
