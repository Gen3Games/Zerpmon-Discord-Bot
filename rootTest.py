import asyncio
from asyncio import Future
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from websockets import client, ConnectionClosed, WebSocketClientProtocol
import json
from web3 import Web3
import asyncio

TEST = True
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
trainer_collection_id = 66660
eq_collection_id = 67684


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
    root_handler = None
    task = None
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
        print(f"Unexpected rootTest error: {e}")
        if root_handler:
            await root_handler.close()
        if task:
            await task
        return False, None


async def test():
    # print(await getOwnedRootNFTs(["0xfFffFfFF0000000000000000000000000003A860"]))0xFFfFFFFf000000000000000000000000000421a4
    print(await getOwnedRootNFTs(["0xFFfFFFFf000000000000000000000000000421a4"]))
    # print("Sending requests again")
    # await asyncio.sleep(10)


# print(asyncio.run(test()))

w3 = Web3(Web3.HTTPProvider('https://root.rootnet.live/archive' if not TEST else 'https://porcini.rootnet.app/archive'))

trn_staking_abi = "[\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_xrpZrpLpToken\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_rootZrpLpToken\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonGenesisNft\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonEvolvedNft\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonTrainersGenesisNft\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonTrainersEvolvedNft\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonEquipmentNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"constructor\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"owner\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"OwnableInvalidOwner\",\n        \"type\": \"error\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"account\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"OwnableUnauthorizedAccount\",\n        \"type\": \"error\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"ReentrancyGuardReentrantCall\",\n        \"type\": \"error\"\n    },\n    {\n        \"anonymous\": false,\n        \"inputs\": [\n            {\n                \"indexed\": true,\n                \"internalType\": \"address\",\n                \"name\": \"previousOwner\",\n                \"type\": \"address\"\n            },\n            {\n                \"indexed\": true,\n                \"internalType\": \"address\",\n                \"name\": \"newOwner\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"OwnershipTransferred\",\n        \"type\": \"event\"\n    },\n    {\n        \"anonymous\": false,\n        \"inputs\": [\n            {\n                \"indexed\": true,\n                \"internalType\": \"address\",\n                \"name\": \"user\",\n                \"type\": \"address\"\n            },\n            {\n                \"indexed\": false,\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            },\n            {\n                \"indexed\": false,\n                \"internalType\": \"string\",\n                \"name\": \"assetType\",\n                \"type\": \"string\"\n            }\n        ],\n        \"name\": \"Staked\",\n        \"type\": \"event\"\n    },\n    {\n        \"anonymous\": false,\n        \"inputs\": [\n            {\n                \"indexed\": true,\n                \"internalType\": \"address\",\n                \"name\": \"user\",\n                \"type\": \"address\"\n            },\n            {\n                \"indexed\": false,\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            },\n            {\n                \"indexed\": false,\n                \"internalType\": \"string\",\n                \"name\": \"assetType\",\n                \"type\": \"string\"\n            }\n        ],\n        \"name\": \"Withdrawn\",\n        \"type\": \"event\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_rootZrpLpToken\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeRootZrpLpToken\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_xrpZrpLpToken\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeXrpZrpLpToken\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonEquipmentNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeZerpmonEquipmentNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonEvolvedNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeZerpmonEvolvedNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonGenesisNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeZerpmonGenesisNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonTrainersEvolvedNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeZerpmonTrainersEvolvedNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"_zerpmonTrainersGenesisNft\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"changeZerpmonTrainersGenesisNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"getAllStakers\",\n        \"outputs\": [\n            {\n                \"internalType\": \"address[]\",\n                \"name\": \"\",\n                \"type\": \"address[]\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"staker\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"getStakedAssets\",\n        \"outputs\": [\n            {\n                \"components\": [\n                    {\n                        \"internalType\": \"uint256\",\n                        \"name\": \"xrpZrpLp\",\n                        \"type\": \"uint256\"\n                    },\n                    {\n                        \"internalType\": \"uint256\",\n                        \"name\": \"rootZrpLp\",\n                        \"type\": \"uint256\"\n                    },\n                    {\n                        \"internalType\": \"uint256[]\",\n                        \"name\": \"zerpmonGenesisNftIds\",\n                        \"type\": \"uint256[]\"\n                    },\n                    {\n                        \"internalType\": \"uint256[]\",\n                        \"name\": \"zerpmonEvolvedNftIds\",\n                        \"type\": \"uint256[]\"\n                    },\n                    {\n                        \"internalType\": \"uint256[]\",\n                        \"name\": \"zerpmonTrainersGenesisNftIds\",\n                        \"type\": \"uint256[]\"\n                    },\n                    {\n                        \"internalType\": \"uint256[]\",\n                        \"name\": \"zerpmonTrainersEvolvedNftIds\",\n                        \"type\": \"uint256[]\"\n                    },\n                    {\n                        \"internalType\": \"uint256[]\",\n                        \"name\": \"zerpmonEquipmentNftIds\",\n                        \"type\": \"uint256[]\"\n                    }\n                ],\n                \"internalType\": \"struct ZerpmonStaking.StakerAssets\",\n                \"name\": \"\",\n                \"type\": \"tuple\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"operator\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"address\",\n                \"name\": \"from\",\n                \"type\": \"address\"\n            },\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"tokenId\",\n                \"type\": \"uint256\"\n            },\n            {\n                \"internalType\": \"bytes\",\n                \"name\": \"data\",\n                \"type\": \"bytes\"\n            }\n        ],\n        \"name\": \"onERC721Received\",\n        \"outputs\": [\n            {\n                \"internalType\": \"bytes4\",\n                \"name\": \"\",\n                \"type\": \"bytes4\"\n            }\n        ],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"owner\",\n        \"outputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"renounceOwnership\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"rootZrpLpToken\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC20\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"stakeRootZrpLpTokens\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"stakeXrpZrpLpTokens\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint8\",\n                \"name\": \"collection\",\n                \"type\": \"uint8\"\n            },\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"nftId\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"stakeZerpmonNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"address\",\n                \"name\": \"newOwner\",\n                \"type\": \"address\"\n            }\n        ],\n        \"name\": \"transferOwnership\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"withdrawRootZrpLpTokens\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"amount\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"withdrawXrpZrpLpTokens\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [\n            {\n                \"internalType\": \"uint8\",\n                \"name\": \"collection\",\n                \"type\": \"uint8\"\n            },\n            {\n                \"internalType\": \"uint256\",\n                \"name\": \"nftId\",\n                \"type\": \"uint256\"\n            }\n        ],\n        \"name\": \"withdrawZerpmonNft\",\n        \"outputs\": [],\n        \"stateMutability\": \"nonpayable\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"xrpZrpLpToken\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC20\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"zerpmonEquipmentNft\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC721\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"zerpmonEvolvedNft\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC721\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"zerpmonGenesisNft\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC721\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"zerpmonTrainersEvolvedNft\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC721\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    },\n    {\n        \"inputs\": [],\n        \"name\": \"zerpmonTrainersGenesisNft\",\n        \"outputs\": [\n            {\n                \"internalType\": \"contract IERC721\",\n                \"name\": \"\",\n                \"type\": \"address\"\n            }\n        ],\n        \"stateMutability\": \"view\",\n        \"type\": \"function\"\n    }\n]"

contract_address = '0xbed9624ea660d9a0d49447499b7aeaef49952ec7'
staking_contract = w3.eth.contract(address=w3.to_checksum_address(contract_address), abi=trn_staking_abi)

# for running sync code asynchronously
executor = ThreadPoolExecutor()

# Helper function to call the contract functions asynchronously
async def call_contract_method_sync(method, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, lambda: method(*args).call())

# Asynchronous function to get TRN staked NFTs
async def get_trn_staked_nfts(addresses):
    zerpmons = []
    trainers = []
    eqs = []

    try:
        # Call the contract method to get all stakers asynchronously
        all_stakers = await call_contract_method_sync(staking_contract.functions.getAllStakers)

        print(f"Total stakers: {len(all_stakers)}")

        # Create a list of tasks for processing stakers
        tasks = []
        for address in all_stakers:
            if address in addresses:
                # Add each contract call to the list of tasks
                tasks.append(call_contract_method_sync(staking_contract.functions.getStakedAssets, address))

        # Execute all the tasks concurrently
        staker_info_raws = await asyncio.gather(*tasks)

        # Process each staker's data
        for staker_info_raw in staker_info_raws:
            zerpmons.extend([int(v) for v in staker_info_raw[2]] + [int(v) for v in staker_info_raw[3]])
            trainers.extend([int(v) for v in staker_info_raw[4]] + [int(v) for v in staker_info_raw[5]])
            eqs.extend([int(v) for v in staker_info_raw[6]])

        return {
            "zerpmons": zerpmons,
            "trainers": trainers,
            "eqs": eqs
        }
    except Exception as e:
        print(f"Error get_trn_staked_nfts: {e}")
        return None

