import asyncio

from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models.requests.account_nfts import AccountNFTs

from xrpl.models.requests import AccountOffers
from xrpl.models.requests import Subscribe
import config
import json
import requests


# look up account nfts
async def get_nfts(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            all_nfts = []

            acct_info = AccountNFTs(
                account=address,
                limit=400,
            )
            response = await client.request(acct_info)
            result = response.result

            while True:

                # print(result)
                length = len(result["account_nfts"])
                print(length)
                all_nfts.extend(result["account_nfts"])
                if "marker" not in result:
                    break
                acct_info = AccountNFTs(
                    account=address,
                    limit=400,
                    marker=result['marker']
                )
                response = await client.request(acct_info)
                result = response.result
                # print(json.dumps(result["account_nfts"], indent=4, sort_keys=True))
            # print(all_nfts)
            return True, all_nfts
    except Exception as e:
        print(e)
        return False, []


# look up account offers
async def get_offers(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            all_offers = []

            acct_info = AccountOffers(
                account=address,
                limit=400,
            )
            response = await client.request(acct_info)
            result = response.result

            while True:

                print(result)
                length = len(result["account_nfts"])
                print(length)
                all_offers.extend(result["account_nfts"])
                if "marker" not in result:
                    break
                acct_info = AccountOffers(
                    account=address,
                    limit=400,
                    marker=result['marker']
                )
                response = await client.request(acct_info)
                result = response.result
                # print(json.dumps(result["account_nfts"], indent=4, sort_keys=True))
            # print(all_nfts)
            return True, all_offers
    except Exception as e:
        print(e)
        return False, []

def get_nft_metadata(uri):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for item in data:
                if item["uri"] == uri:
                    return item
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")

# print(get_nft_metadata("697066733A2F2F516D57366677545953376F6741614C6159576247766658546A786758585357734643535256654E544A70396B347A2F3231382E6A736F6E"))