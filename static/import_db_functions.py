import pymongo
import csv
import requests

client = pymongo.MongoClient('mongodb://localhost:27017/')
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


def import_moves():
    with open('Zerpmon_Moves_-_Move_List_1.csv', 'r') as csvfile:
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
    with open('Zerpmon_Moves_-_Zerpmon_Movesets_1.csv', 'r') as csvfile:
        collection = db['MoveSets']
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
                    'collection': row[2],
                    'moves': [
                        {'name': row[5], 'dmg': int(row[6]) if row[6] != "" else "", 'type': row[7], 'id': row[8],
                         'percent': row[9].replace("%", ""), 'color': header[4]},
                        {'name': row[10], 'dmg': int(row[11]) if row[11] != "" else "", 'type': row[12], 'id': row[13],
                         'percent': row[14].replace("%", ""), 'color': header[9]},
                        {'name': row[15], 'dmg': int(row[16]) if row[16] != "" else "", 'type': row[17], 'id': row[18],
                         'percent': row[19].replace("%", ""), 'color': header[14]},
                        {'name': row[20], 'dmg': int(row[21]) if row[21] != "" else "", 'type': row[22], 'id': row[23],
                         'percent': row[24].replace("%", ""), 'color': header[19]},
                        {'name': row[25], 'stars': row[26], 'id': row[27], 'percent': row[28].replace("%", ""),
                         'color': header[24]},
                        {'name': row[29], 'stars': row[30], 'id': row[31], 'percent': row[32].replace("%", ""),
                         'color': header[28]},
                        {'name': row[33], 'id': row[34], 'percent': row[35].replace("%", ""), 'color': header[32]},
                        {'name': row[36], 'id': row[37], 'percent': row[38].replace("%", ""), 'color': header[35]},
                    ],
                    'nft_id': row[39]
                }
                collection.update_one({'name': row[1]}, {'$set': doc}, upsert=True)
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


def import_attrs_img():
    data = get_all_z()
    for i in data:
        id = i['nft_id']
        if 'image' in i and 'attributes' in i:
            continue
        path = f"./static/images/{i['name']}.png"
        rr2 = requests.get(
            f"https://bithomp.com/api/cors/v2/nft/{id}?uri=true&metadata=true&history=true&sellOffers=true&buyOffers=true&offersValidate=true&offersHistory=true")
        meta = rr2.json()['metadata']['attributes']
        url = rr2.json()['metadata']['image']
        print(url)
        update_type(i['name'], meta)
        update_image(i['name'], url)


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


# import_moves()
import_movesets()
# import_level()
import_attrs_img()
clean_attrs()