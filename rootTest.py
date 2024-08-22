import asyncio
from asyncio import Future
from typing import List, Optional
from websockets import client, ConnectionClosed, WebSocketClientProtocol
import json

# Define the WebSocket URL
url = "wss://root.rootnet.live/archive/ws"


# Define the JSON-RPC payload
def get_owned_tokens_payload(address: str, collectionID: int, limit=1000):
    return {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "nft_ownedTokens",
        "params": [
            collectionID,  # Collection ID
            # "0xFFFFFFff00000000000000000000000000036a03",
            address,  # Account address
            0,  # Marker/Serial Number
            limit,  # Replace with actual limit
        ]
    }


def get_nft_uri_payload(collectionID: int, tokenID: int):
    return {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "nft_tokenUri",
        "params": [
            (collectionID, tokenID)  # Token ID
        ]
    }


class JsonRequest:
    fut: Future
    jsonParsed: str

    def __init__(self, fut, json_payload):
        self.fut = fut
        self.jsonParsed = json.dumps(json_payload)


class JsonResult:
    def __init__(self, success: bool, data: dict | str):
        self.success = success
        self.data = data


class RootWebsocket:
    def __init__(self):
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.json_payloads: List[JsonRequest] = []
        self.close_ws = False

    async def close(self):
        self.close_ws = True

    async def on_message(self, message: str, fut: Future):
        response_data = json.loads(message)
        if "error" in response_data:
            print("Error:", response_data["error"])
            fut.set_result(JsonResult(False, response_data["error"]))
        else:
            print("Result:", response_data["result"])
            fut.set_result(JsonResult(True, response_data["result"]))

    async def request(self, payload: dict) -> JsonResult:
        future = asyncio.Future()
        self.json_payloads.append(JsonRequest(fut=future, json_payload=payload))
        return await future

    async def run_ws(self):
        while True:
            print("Running root ws...")
            if self.close_ws:
                print("Closing root ws...")
                return 1
            if self.json_payloads:
                try:
                    async for ws in client.connect(url):
                        self.websocket = ws
                        try:
                            if len(self.json_payloads) > 0:
                                current_request = self.json_payloads.pop(0)  # Safer pop
                                print(current_request.jsonParsed)
                                await asyncio.wait_for(ws.send(current_request.jsonParsed), timeout=10)
                                # Set a timeout for receiving a message
                                try:
                                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                                    await self.on_message(msg, current_request.fut)
                                except asyncio.TimeoutError:
                                    print("Timeout: No message received within 10 seconds.")
                                    current_request.fut.set_result(JsonResult(False, "Timeout"))
                            elif self.close_ws:
                                break
                        except ConnectionClosed:
                            continue
                except asyncio.TimeoutError:
                    print("Timeout during connection.")
                except Exception as e:
                    print(f"Unknown error: {e}")
            else:
                await asyncio.sleep(1)


zerp_collection_id = 65636
trainer_collection_id = None
eq_collection_id = None


async def getOwnedRootNFTs(addresses: List[str], fetchMetadataUri=False):
    """
    fetchMetadataUri=False Returns tuple(
    bool,
    address -> {zerp_collection_id: [token_id_1, token_id_2, ...], ...}
    )
    mapping

    fetchMetadataUri=True Returns tuple(
    bool,
    address -> {zerp_collection_id: [{'token_id': token_id, 'uri': metadata_url}], ...}
    )
    """
    try:
        root_handler = RootWebsocket()
        task = asyncio.create_task(root_handler.run_ws())
        result = {
            address: {zerp_collection_id: [], trainer_collection_id: [], eq_collection_id: []}
            for address in addresses}
        for address in addresses:
            try:
                for collection_id in [zerp_collection_id, trainer_collection_id, eq_collection_id]:
                    if collection_id is None:
                        continue
                    data = await root_handler.request(
                        get_owned_tokens_payload(address, collection_id))
                    owned_nft_data = data.data
                    token_ids = owned_nft_data[2]
                    print(len(token_ids))
                    if fetchMetadataUri:
                        for token_id in token_ids:
                            data = await root_handler.request(get_nft_uri_payload(zerp_collection_id, token_id))
                            bytes_uri = bytes(data.data)
                            metadata_url = bytes_uri.decode('utf-8')
                            print(metadata_url, bytes_uri.hex())
                            result[address][collection_id].append({'token_id': token_id, 'uri': metadata_url})
                    else:
                        result[address][collection_id] = token_ids
            except Exception as e:
                print(e)
                await root_handler.close()
                await task
                return False, None

        await root_handler.close()
        await task
        return True, result
    except:
        return False, None


async def test():

    # print(await getOwnedRootNFTs(["0xfFffFfFF0000000000000000000000000003A860"]))0xFFfFFFFf000000000000000000000000000421a4
    print(await getOwnedRootNFTs(["0xFFfFFFFf000000000000000000000000000421a4"]))
    # print("Sending requests again")
    # await asyncio.sleep(10)


print(asyncio.run(test()))
