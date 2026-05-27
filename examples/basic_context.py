import asyncio

from sre_web_inspector import BrowserContextManager


async def main():
    async with BrowserContextManager(headless=False, slow_mo=300, user_data_dir="./user-data") as cm:
        await cm.goto("https://example.com")
        print(await cm.title())
        await cm.screenshot("outputs/screenshots/example.png")
        await cm.dump_network_records("outputs/network/example.json")


if __name__ == "__main__":
    asyncio.run(main())
