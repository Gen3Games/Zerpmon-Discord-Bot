import json
import time 

JSON_FILE = "static/auction.json"

def register_auction(nft_id, price, duration, duration_type,name,endtime):
    with open(JSON_FILE, "r") as f:
        data = json.load(f) 
        data["auctions"].append({ 
            "nft_id": nft_id,
            "floor": price,
            "duration": duration,
            "duration_type": duration_type,
            "start_time": int(time.time()),
            "end_time": endtime,
            "name": name,
            "bids_track": [] #list of dicts, each dict has bidder and bid amount
        })
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)

def get_auctions():
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        return data["auctions"]

def get_auctions_names():
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        names = []
        for auction in data["auctions"]:
            names.append(auction["name"])
        return names
    
def get_auction_by_name(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                return auction
        return None
    
def check_auction_exists(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                return True
        return False
    
def update_auction_endtime(name, endtime):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                auction["end_time"] = endtime
                break
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)

def update_auction_bid(name, bidder, bid):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                auction["bids_track"].append({"bidder": bidder, "bid": bid})
                break
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)

def get_highest_bidder(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                if len(auction["bids_track"]) == 0:
                    return None
                return auction["bids_track"][-1]["bidder"]
        return None
    
def get_highest_bid(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                if len(auction["bids_track"]) == 0:
                    return auction["floor"]
                return auction["bids_track"][-1]["bid"]
        return None
    
def delete_auction(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                data["auctions"].remove(auction)
                break
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)

def check_auction_end(name):
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
        for auction in data["auctions"]:
            if auction["name"] == name:
                return auction["end_time"] <= int(time.time())
        return None