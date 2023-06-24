import json
import time

import requests

import db_query
from pymongo import MongoClient, ReturnDocument
import config

client = MongoClient(config.MONGO_URL)
db = client['Zerpmon']

# Instantiate Static collections

zerpmon_collection = db['MoveSets']
move_collection = db['MoveList']


def set_image_and_attrs():
    data = db_query.get_all_z()
    for i in data:

        if ('image' in i and 'attributes' in i) or 'nft_id' not in i:
            continue

        id = i['nft_id']
        rr2 = requests.get(
            f"https://bithomp.com/api/cors/v2/nft/{id}?uri=true&metadata=true&history=false&sellOffers=false&buyOffers"
            f"=false&offersValidate=false&offersHistory=false")
        print(rr2.json())
        meta = rr2.json()['metadata']['attributes']
        url = rr2.json()['metadata']['image']
        print(url)
        db_query.update_type(i['name'], meta)
        db_query.update_image(i['name'], url)


def clean_attrs():
    all_z = zerpmon_collection.find()

    for i in all_z:
        for _i, j in enumerate(i['attributes']):
            if j['trait_type'] == 'Type':
                i['attributes'][_i]['value'] = str(j['value']).lower().title()
                r = zerpmon_collection.find_one_and_update({'name': i['name']},
                                                           {'$set': {'attributes': i['attributes']}})
                print(r)


def check_move_format(z_obj):
    if all(key in z_obj for key in ['name', 'nft_id', 'moves']):
        # Correct name
        z_obj['name'] = z_obj['name'].lower().title()

        # Loop over moves
        for i, move in enumerate(z_obj['moves']):
            print(move)
            # Check name and convert to correct format
            if 'name' in move:
                z_obj['moves'][i]['name'] = move['name'].title()
            else:
                return False, None

            # Check id
            if 'id' in move:
                pass
            else:
                return False, None

            # Check color and convert to correct format
            if 'color' in move:
                z_obj['moves'][i]['color'] = move['color'].lower()
                if move['color'].lower() in list(config.COLOR_MAPPING.keys()):
                    pass
                else:
                    return False, None
            else:
                return False, None

            # Check percent and convert to correct format
            if 'percent' in move:
                z_obj['moves'][i]['percent'] = str(move['percent'].replace("%", ""))
                if float(move['percent'].replace("%", "")):
                    pass
                else:
                    return False, None
            else:
                return False, None

            # Check dmg and convert to correct format
            if 'dmg' in move:
                z_obj['moves'][i]['dmg'] = int(move['dmg'])
            elif i in [2, 3, 4]:
                pass
            else:
                return False, None

            # Check type and convert to correct format
            if 'type' in move:
                z_obj['moves'][i]['type'] = move['type'].replace(" ", "").lower().title()
            elif i in [2, 3, 4]:
                pass
            else:
                return False, None

            # Check stars and convert to correct format
            if 'stars' in move:
                z_obj['moves'][i]['stars'] = move['stars'].replace(" ", "").lower().title()
            elif i != 2:
                pass
            else:
                return False, None

        return True, z_obj
    else:
        return False, None
