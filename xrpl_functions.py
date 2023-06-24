import asyncio

from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models.requests.account_nfts import AccountNFTs
from xrpl.models.requests import AccountTx
from xrpl.models.requests import Subscribe
import config
import json
import requests


# look up account nfts
async def get_nfts(address):
    try:
        client = AsyncJsonRpcClient("https://xrplcluster.com/")
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
    except:
        return False, []


async def get_nft_metadata(uri):
    # Convert the URI from hex to ASCII
    ascii_uri = bytes.fromhex(uri).decode('ascii')
    ascii_uri = ascii_uri.replace("ipfs://", "")
    print('https://ipfs.io/ipfs/' + ascii_uri)
    # Make the API request
    for base_url in config.BASE_URLS:
        try:
            if "https:/" in ascii_uri:
                response = requests.get(ascii_uri)
            else:
                response = requests.get(base_url + ascii_uri)

            # Parse the response as JSON
            print(response.json())
            # metadata = json.loads(response.content)

            # Print the metadata
            # print(metadata)
            return response.json()
        except Exception as e:
            print(f"ERROR in getting metadata: {e}")

