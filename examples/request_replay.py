import asyncio

from sre_web_inspector import BrowserContextManager, RequestReplayer


async def main():
    async with BrowserContextManager(user_data_dir="./user-data", headless=False) as cm:
        replayer = RequestReplayer(cm.context, output_dir="outputs/replay")
        result = await replayer.get(
            "https://internal.example.com/api/middleware",
            name="middleware_datas",
            params={"namespace": "default", "pageSize": 100},
        )
        print(result.status)
        print(result.output_path)


if __name__ == "__main__":
    asyncio.run(main())
