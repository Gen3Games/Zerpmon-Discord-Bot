import asyncio
import traceback
from statistics import mean

from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models import IssuedCurrency
from xrpl.models.requests.account_nfts import AccountNFTs

from xrpl.models.requests import AccountOffers, BookOffers
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


async def get_zrp_price():
    try:
        if config.zrp_price is None:
            async with AsyncWebsocketClient(config.NODE_URL) as client:
                taker_pays = IssuedCurrency(
                    currency="ZRP",
                    issuer=config.ISSUER['ZRP']
                )
                req_json = {
                    "taker_gets": {
                        "currency": "XRP"
                    },
                    "taker_pays": taker_pays,
                    "limit": 20
                }

                # acct_info = BookOffers.from_dict(req_json)
                # response = await client.request(acct_info)
                # result = response.result

                req_json["taker_gets"], req_json["taker_pays"] = req_json["taker_pays"], req_json["taker_gets"]
                acct_info = BookOffers.from_dict(req_json)
                response2 = await client.request(acct_info)
                result2 = response2.result
                max_p, min_p = None, None
                # if 'offers' in result:
                #     print(result)
                #     prices = []
                #     for order in result['offers']:
                #         xrp = float(order['TakerGets']) / 10 ** 6
                #         zrp = float(order['TakerPays']['value'])
                #         price = xrp / zrp
                #         prices.append(price)
                #     if len(prices) > 0:
                #         max_p = max(prices)
                #         print(max_p, prices)
                if 'offers' in result2:
                    print(result2)
                    prices = []
                    for order in result2['offers']:
                        xrp = float(order['TakerPays']) / 10 ** 6
                        zrp = float(order['TakerGets']['value'])
                        price = xrp / zrp
                        prices.append(price)
                    if len(prices) > 0:
                        min_p = min(prices)
                        print(min_p, prices)
                if max_p is not None and min_p is not None:
                    last_zrp_p = mean([max_p, min_p])
                config.zrp_price = max_p if min_p is None else (min_p if max_p is None else last_zrp_p)
                return True, config.zrp_price
        else:
            return True, config.zrp_price
    except Exception as e:
        print(traceback.format_exc())
        return False, config.zrp_price


async def get_zrp_price_api():
    # req = requests.post('https://api.xrpl.to/api/search', json={'search': 'zrp'})
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "ripple",
            "vs_currencies": "usd"
        }
        response = requests.get(url, params=params)
        data = response.json()
        xrp_price = float(data["ripple"]["usd"])
        req = requests.get('https://api.xrpl.to/api/graph/4b53d132672efcbee4386ab35d64fd14?range=1D')
        result = req.json()
        token_price = float(result['history'][-1][-1])
        return token_price/xrp_price
    except Exception as e:
        print("Error occurred while fetching XRP price:", e)
        return None


# asyncio.run(get_zrp_price_api())
# res = asyncio.run(get_zrp_price())
# print(res)


def get_nft_metadata(uri):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for item in data:
                if item["uri"] == uri:
                    return item['metadata']
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

# print(get_nft_metadata("697066733A2F2F516D57366677545953376F6741614C6159576247766658546A786758585357734643535256654E544A70396B347A2F3231382E6A736F6E"))
