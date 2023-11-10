import json

import pymongo
import csv
import requests
from pymongo import ReturnDocument

import config

client = pymongo.MongoClient(config.MONGO_URL)
# client = pymongo.MongoClient("mongodb://127.0.0.1:27017")
db = client['Zerpmon']



# users_c = db['users']
# users_c.drop()


def get_all_z():
    zerpmon_collection = db['MoveSets']
    data = zerpmon_collection.find({})
    return [i for i in data]


def update_image(name, url):
    zerpmon_collection = db['MoveSets']
    zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'image': url}})


def update_type(name, attrs):
    zerpmon_collection = db['MoveSets']
    zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'attributes': attrs}})


def import_boxes():
    collection = db['gift']
    with open('Zerpmon_Gift_Box.csv', 'r') as csvfile:

        csvreader = csv.reader(csvfile)
        for row in csvreader:
            if "Row Labels" in row[0]:
                continue
            # Insert the row data to MongoDB
            collection.update_one({'address': row[0]}, {'$set': {
                'address': row[0],
                'zerpmon_box': int(row[1])
            }}, upsert=True)
    with open('Xscape_Gift_Box.csv', 'r') as csvfile:
        csvreader = csv.reader(csvfile)
        for row in csvreader:
            if "Row Labels" in row[0]:
                continue
            # Insert the row data to MongoDB
            collection.update_one({'address': row[0]}, {'$set': {
                'address': row[0],
                'xscape_box': int(row[1])
            }}, upsert=True)


def import_moves():
    with open('Zerpmon_Moves_-_Move_List_091123.csv', 'r') as csvfile:
        collection = db['MoveList']
        collection.drop()
        csvreader = csv.reader(csvfile)
        for row in csvreader:
            if row[1] == "":
                continue
            # Insert the row data to MongoDB
            collection.insert_one({
                'move_id': row[0],
                'move_name': row[1],
                'type': row[2],
                'dmg': row[3],
                'color': row[4],
                'notes': row[5],
            })


def import_movesets():
    with open('Zerpmon_Moves_-_Zerpmon_Movesets_091123_For_Glad.csv', 'r') as csvfile:
        collection = db['MoveSets']
        # c2 = db['MoveSets2']
        # c2.drop()
        csvreader = csv.reader(csvfile)
        header = next(csvreader)  # Skip the header row
        header = [field.lower().split()[0] for field in header if field]
        print(header)

        for row in csvreader:
            # return
            # Remove empty fields from the row
            row = [field for field in row if field != "0.003083061299"]

            if row[38] == "":
                continue

            # Insert the row data to MongoDB
            try:
                doc = {
                    'number': row[0],
                    'name': row[1],
                    # 'collection': row[2],
                    'moves': [
                        {'name': row[4], 'dmg': int(row[5]) if row[5] != "" else "", 'type': row[6], 'id': row[7],
                         'percent': row[8].replace("%", ""), 'color': header[3]},
                        {'name': row[9], 'dmg': int(row[10]) if row[10] != "" else "", 'type': row[11], 'id': row[12],
                         'percent': row[13].replace("%", ""), 'color': header[8]},
                        {'name': row[14], 'dmg': int(row[15]) if row[15] != "" else "", 'type': row[16], 'id': row[17],
                         'percent': row[18].replace("%", ""), 'color': header[13]},
                        {'name': row[19], 'dmg': int(row[20]) if row[20] != "" else "", 'type': row[21], 'id': row[22],
                         'percent': row[23].replace("%", ""), 'color': header[18]},
                        {'name': row[24], 'stars': row[25], 'id': row[26], 'percent': row[27].replace("%", ""),
                         'color': header[23]},
                        {'name': row[28], 'stars': row[29], 'id': row[30], 'percent': row[31].replace("%", ""),
                         'color': header[27]},
                        {'name': row[32], 'id': row[33], 'percent': row[34].replace("%", ""), 'color': header[31]},
                        {'name': 'Miss', 'id': row[36], 'percent': row[37].replace("%", ""), 'color': header[34]},
                    ],
                    'nft_id': row[38]
                }

                # doc = {
                #     'number': row[0],
                #     'name': row[1],
                #     'collection': row[2],
                #     'moves': [
                #         {'name': row[5], 'dmg': int(row[6]) if row[6] != "" else "", 'type': row[7], 'id': row[8],
                #          'percent': row[9].replace("%", ""), 'color': header[4]},
                #         {'name': row[10], 'dmg': int(row[11]) if row[11] != "" else "", 'type': row[12], 'id': row[13],
                #          'percent': row[14].replace("%", ""), 'color': header[9]},
                #         {'name': row[15], 'dmg': int(row[16]) if row[16] != "" else "", 'type': row[17], 'id': row[18],
                #          'percent': row[19].replace("%", ""), 'color': header[14]},
                #         {'name': row[20], 'dmg': int(row[21]) if row[21] != "" else "", 'type': row[22], 'id': row[23],
                #          'percent': row[24].replace("%", ""), 'color': header[19]},
                #         {'name': row[25], 'stars': row[26], 'id': row[27], 'percent': row[28].replace("%", ""),
                #          'color': header[24]},
                #         {'name': row[29], 'stars': row[30], 'id': row[31], 'percent': row[32].replace("%", ""),
                #          'color': header[28]},
                #         {'name': row[33], 'id': row[34], 'percent': row[35].replace("%", ""), 'color': header[32]},
                #         {'name': row[36], 'id': row[37], 'percent': row[38].replace("%", ""), 'color': header[35]},
                #     ],
                #     'nft_id': row[39]
                # }
                collection.update_one({'name': row[1]}, {'$set': doc}, upsert=True)
                # c2.insert_one(document=doc)
            except Exception as e:
                print(e, '\n', row)


# import_movesets()

def import_level():
    collection = db['levels']
    collection.drop()
    with open('Zerpmon_EXP_Scaling_for_Missions.csv', 'r') as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip the header row
        for row in reader:
            # Replace empty values with ""
            row = ["" if x.strip() == "" else x for x in row]
            print(row)
            # Convert XP Required per level, Total XP Earned, Wins, Mission Refreshes and EXP Per Win to integers
            collection.insert_one({
                'level': int(row[0]),
                'xp_required': int(row[1]),
                'total_xp': int(row[2]),
                'wins_needed': int(row[3]),
                'revive_potion_reward': 0 if row[4].strip() == "" else int(row[4]),
                'mission_potion_reward': 0 if row[5].strip() == "" else int(row[5]),
            })


def check_nft_cached(id, data):
    for i in data:
        if i['nftid'] == id:
            return True
    return False


def get_cached():
    with open("./metadata.json", "r") as f:
        return json.load(f)


def import_attrs_img():
    data = get_all_z()
    # tba = get_cached()  # [{nftid, metadata, uri},...]
    for i in data:
        id = i['nft_id']
        if 'image' in i and 'attributes' in i:
            continue
        path = f"./static/images/{i['name']}.png"
        rr2 = requests.get(
            f"https://bithomp.com/api/cors/v2/nft/{id}?uri=true&metadata=true&history=true&sellOffers=true&buyOffers=true&offersValidate=true&offersHistory=true")
        res = rr2.json()
        print(i, res)
        meta = res['metadata']['attributes']
        url = res['metadata']['image']
        print(url)
        update_type(i['name'], meta)
        update_image(i['name'], url)
    #     tba.append({
    #         "nftid": id,
    #         "metadata": res['metadata'],
    #         "uri": res['uri'],
    #     })
    # with open("./metadata.json", "w") as f:
    #     json.dump(tba, f)


def clean_attrs():
    zerpmon_collection = db['MoveSets']
    all_z = zerpmon_collection.find()

    for i in all_z:
        for _i, j in enumerate(i['attributes']):
            if j['trait_type'] == 'Type':
                i['attributes'][_i]['value'] = str(j['value']).lower().title()
                r = zerpmon_collection.find_one_and_update({'name': i['name']},
                                                           {'$set': {'attributes': i['attributes']}})
                print(r)
    c2 = db['MoveSets2']
    c2.drop()
    for doc in zerpmon_collection.find():
        del doc['_id']
        c2.insert_one(doc)


def save_new_zerpmon(zerpmon):
    zerpmon_collection = db['MoveSets']
    print(zerpmon)

    doc_str = json.dumps(zerpmon)
    zerpmon = json.loads(doc_str)

    result = zerpmon_collection.update_one(
        {'name': zerpmon['name']},
        {'$set': zerpmon},
        upsert=True)

    if result.upserted_id:
        print(f"Created new Zerpmon with id {result.upserted_id}")
        return f"Successfully added a new Zerpmon {zerpmon['name']}"
    else:
        print(f"Updated Zerpmon with name {zerpmon['name']}")
        return f"Successfully updated Zerpmon {zerpmon['name']}"


def update_all_zerp_moves():
    for document in db['MoveSets'].find():
        del document['_id']
        if 'level' in document and document['level'] / 10 >= 1:
            miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
            percent_change = 3.33 * (document['level'] // 10)
            if percent_change == 9.99:
                percent_change = 10
            percent_change = percent_change if percent_change < miss_percent else miss_percent
            count = len([i for i in document['moves'] if i['name'] != "" and i['color'] != "blue"]) - 1
            print(document)
            for i, move in enumerate(document['moves']):
                if move['color'] == 'miss':
                    move['percent'] = str(round(float(move['percent']) - percent_change, 2))
                    document['moves'][i] = move
                elif move['name'] != "" and float(move['percent']) > 0 and move['color'] != "blue":
                    move['percent'] = str(round(float(move['percent']) + (percent_change / count), 2))
                    document['moves'][i] = move
            save_new_zerpmon(document)
        w_candy = document.get('white_candy', 0)
        g_candy = document.get('gold_candy', 0)
        if w_candy > 0:

            original_zerp = db['MoveSets2'].find_one({'name': document['name']})
            for i in range(w_candy):
                for i, move in enumerate(document['moves']):
                    if move['color'].lower() == 'white':
                        document['moves'][i]['dmg'] = round(
                            document['moves'][i]['dmg'] + (original_zerp['moves'][i]['dmg'] * 0.02),
                            1)
            save_new_zerpmon(document)
        if g_candy > 0:
            original_zerp = db['MoveSets2'].find_one({'name': document['name']})
            for i in range(g_candy):
                for i, move in enumerate(document['moves']):
                    if move['color'].lower() == 'gold':
                        document['moves'][i]['dmg'] = round(
                            document['moves'][i]['dmg'] + original_zerp['moves'][i]['dmg'] * 0.02,
                            1)
            save_new_zerpmon(document)


def get_issuer_nfts_data(issuer):
    try:
        print("get_collection_5kk")
        url = f"https://bithomp.com/api/cors/v2/nfts?list=nfts&issuer={issuer}"
        response = requests.get(url)
        response = response.json()

        nfts = response['nfts']

        marker = False
        markerVal = ''
        if 'marker' in response:
            marker = True
            markerVal = response['marker']

        while marker:
            url2 = f"https://bithomp.com/api/cors/v2/nfts?list=nfts&issuer={issuer}&marker={markerVal}"
            response2 = requests.get(url2)
            response2 = response2.json()

            nfts2 = response2['nfts']
            nfts.extend(nfts2)

            if 'marker' in response2:
                marker = True
                markerVal = response2['marker']
            else:
                marker = False

        print("Total NFTs: ", len(nfts))
        return nfts
    except Exception as e:
        print(str(e), ' error')


def cache_data():
    try:
        z_nfts = get_issuer_nfts_data('rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME')
        nfts = get_issuer_nfts_data('rXuRpzTATAm3BNzWNRLmzGwkwJDrHy6Jy')
        e_nfts = get_issuer_nfts_data('rEQQ8tTnJm4ECbPv71K9syrHrTJTv6DX3T')
        z_nfts.extend(nfts)
        z_nfts.extend(e_nfts)
        tba = get_cached()
        for nft in z_nfts:
            if not check_nft_cached(nft['nftokenID'], tba):
                for _i, j in enumerate(nft['metadata']['attributes']):
                    if j['trait_type'] == 'Type':
                        nft['metadata']['attributes'][_i]['value'] = str(j['value']).strip().lower().title()
                tba.append({
                    'nftid': nft['nftokenID'],
                    'metadata': nft['metadata'],
                    'uri': nft['uri']
                })
        with open("./metadata.json", "w") as f:
            json.dump(tba, f)

    except Exception as e:
        print(str(e), ' error')


def reset_all_gyms():
    users_collection = db['users']
    old = users_collection.find()
    for user in old:
        gym_obj = user.get('gym', {})
        gym_obj['won'] = {}
        gym_obj['active_t'] = 0
        gym_obj['gp'] = 0
        query = {'$set': {'gym': gym_obj}}
        r = users_collection.find_one_and_update({'discord_id': user['discord_id']},
                                                 query,
                                                 return_document=ReturnDocument.AFTER)


def import_equipments():
    with open('Zerpmon_Moves_-_Equipment.csv', 'r') as csvfile:
        collection = db['Equipment']
        collection.drop()
        csvreader = csv.reader(csvfile)
        for row in csvreader:
            if row[1] == "":
                continue
            # Insert the row data to MongoDB
            collection.insert_one({
                'type': row[0].lower().title(),
                'name': row[-1],
                'notes': [i for i in row[1:-1] if i != ""]
            })


# import_boxes()
import_moves()
import_movesets()
# import_level()
import_attrs_img()
clean_attrs()
update_all_zerp_moves()
cache_data()
# import_equipments()

# reset_all_gyms()
