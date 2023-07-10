import asyncio

from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models.requests.account_nfts import AccountNFTs

from xrpl.models.requests import AccountOffers, AccountInfo
from xrpl.models.requests import Subscribe
import config
import json
import requests
from xrpl.utils import drops_to_xrp

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

def get_nft_metadata_by_id(nftid):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for item in data:
                if item["nftid"] == nftid:
                    return item
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")

async def get_xrp_balance(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            acct_info = AccountInfo(
                account=address,
                ledger_index="validated",
                queue=True,
            )
            response = await client.request(acct_info)
            result = response.result
            return drops_to_xrp(result["account_data"]["Balance"])
    except Exception as e:
        print(e)
        return 0