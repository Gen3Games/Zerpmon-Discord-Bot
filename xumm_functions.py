import asyncio
import json
import time

import requests
import config

url = "https://xumm.app/api/v1/platform/payload"
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "X-API-Key": config.XUMM_API_KEY,
    "X-API-Secret": config.XUMM_SECRET
}


async def gen_signIn_url():
    payload = {
        "txjson": {"TransactionType": "SignIn"},
        "options": {
            "pathfinding_fallback": False,
            # "force_network": "N/A"
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )

    print(r_remain)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    print(json.dumps(res_json, indent=2))

    return res_json['uuid'], res_json['refs']['qr_png'], res_json['next']['always']


# u, link = gen_signIn_url()


async def check_sign_in(uuid):
    n_url = f'{url}/{uuid}'

    response = requests.get(n_url, headers=headers)

    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )

    print(r_remain)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    if res_json['meta']['signed']:
        address = res_json['response']['account']
        return True, address
    else:
        return False, None


# print(check_sign_in("2c1e23f9-a4b0-4c74-a94d-43c892eaf586"))


async def gen_txn_url(to_address, from_address, amount):
    amount = int(amount)
    tjson = {
        "TransactionType": "Payment",
        "Account": f"{from_address}",
        "Destination": to_address,
        "Amount": f"{amount}",
        "SourceTag": 13888813
    }
    payload = {
        "txjson": tjson,
        "options": {
            "pathfinding_fallback": False,
            # "force_network": "N/A"
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )

    print(r_remain, amount)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    print(json.dumps(res_json, indent=2))

    return res_json['uuid'], res_json['refs']['qr_png'], res_json['next']['always']


async def gen_nft_txn_url(from_address, nft_id, destination = config.WAGER_ADDR):
    tjson = {
        "TransactionType": "NFTokenCreateOffer",
        "Account": from_address,
        "NFTokenID": nft_id,
        "Amount": "0",
        "Flags": 1,
        "Destination": destination,
        "SourceTag": 13888813
    }
    payload = {
        "txjson": tjson,
        "options": {
            "pathfinding_fallback": False,
            # "force_network": "N/A"
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )

    print(r_remain)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    print(json.dumps(res_json, indent=2))

    return res_json['uuid'], res_json['refs']['qr_png'], res_json['next']['always']


async def gen_nft_accept_txn(from_address, offer, nft_id):
    tjson = {
        "Account": from_address,
        "NFTokenSellOffer": offer,
        "TransactionType": "NFTokenAcceptOffer",
        "SourceTag": 13888813
    }
    payload = {
        "txjson": tjson,
        "options": {
            "pathfinding_fallback": False,
            # "force_network": "N/A"
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )

    print(r_remain)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    print(json.dumps(res_json, indent=2))

    return res_json['uuid'], res_json['refs']['qr_png'], res_json['next']['always']


async def gen_zrp_txn_url(to_address, from_address, amount):
    amount = float(amount)
    tjson = {
        "TransactionType": "Payment",
        "Account": f"{from_address}",
        "Destination": to_address,
        "Amount": {
            "currency": "ZRP",
            "value": f'{amount}',
            "issuer": config.ISSUER['ZRP']
        },
        "SourceTag": 13888813
    }
    payload = {
        "txjson": tjson,
        "options": {
            "pathfinding_fallback": False,
            # "force_network": "N/A"
        }
    }
    print(amount)
    return await construct_xumm_payload(payload)


async def construct_xumm_payload(payload):
    response = requests.post(url, json=payload, headers=headers)
    res_json = response.json()
    r_remain = response.headers['x-ratelimit-remaining']
    # print(json.dumps(res_json, indent=2), )
    print(r_remain)
    if float(r_remain) < 2:
        sleep_timer = float(response.headers['x-ratelimit-reset']) - time.time()
        await asyncio.sleep(sleep_timer)

    print(json.dumps(res_json, indent=2))

    return res_json['uuid'], res_json['refs']['qr_png'], res_json['next']['always']
