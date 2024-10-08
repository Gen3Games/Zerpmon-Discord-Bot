import asyncio
import json
import random
import re
import time
import traceback
from typing import TypedDict
import pymongo
import csv
import requests
from pymongo import ReturnDocument
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import NFTsByIssuer
from xrpl.utils import hex_to_str

import config
import config_extra

client = pymongo.MongoClient(config.MONGO_URL)
# client = pymongo.MongoClient("mongodb://127.0.0.1:27017")
db = client['Zerpmon']
print([i['name'] for i in db.list_collections()])

# exit(1)
# users_c = db['users']


class NFTDict(TypedDict):
    nft_id: str
    ledger_index: int
    owner: str
    is_burned: bool
    uri: str
    flags: int
    transfer_fee: int
    issuer: str
    nft_taxon: int
    nft_serial: int


async def fetchNFTsByIssuer(issuer_address, limit=10000, delay_per_request=1):
    try:
        # Can switch to private node after installing clio server
        ws_client = AsyncWebsocketClient(config_extra.CLIO_WS_URL)
        await ws_client.open()
        all_nfts: [NFTDict] = []

        acct_info = NFTsByIssuer(
            issuer=issuer_address,
            ledger_index="validated",
            marker=None,
            limit=400
        )
        response = await ws_client.request(acct_info)
        result = response.result
        print(result)
        while True:
            await asyncio.sleep(delay_per_request)
            # print(result)
            if 'nfts' not in result or len(all_nfts) >= limit:
                break
            length = len(result["nfts"])
            print(length)
            all_nfts.extend(result['nfts'])
            if "marker" not in result:
                break
            acct_info = NFTsByIssuer(
                issuer=issuer_address,
                ledger_index="validated",
                marker=result['marker'],
                limit=400
            )
            response = await ws_client.request(acct_info)
            result = response.result
        print(len(all_nfts))
        await ws_client.close()
        return all_nfts
    except Exception as e:
        print(traceback.format_exc())
        return None


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


def extract_numbers(input_string):
    pattern = r'[-+]?\d*\.\d+|\d+'  # This pattern captures both integers and floating-point numbers

    numbers = re.findall(pattern, input_string)

    # Convert the strings to float
    numbers = [float(num) for num in numbers]

    return numbers


def are_effects_equal(effect1, effect2):
    for k, v in effect1.items():
        if k != 'value':
            if effect1[k] != effect2.get(k):
                return False
    return True


def get_unique_id(entries: list[dict], new_entry: dict):
    for idx, entry in enumerate(entries):
        if are_effects_equal(new_entry, entry):
            return idx + 1
    entries.append(new_entry)
    return len(entries)


def get_effects(entries, l_effect, disabled):
    match = extract_numbers(l_effect)
    if disabled:
        return {
                "ko_against": None,
                "unit": "flat",
                "target": "opponent",
                "move_type": [
                    "blue"
                ],
            'disabled': True
            }
    effect = {'disabled': False}
    if 'until ko' in l_effect:
        effect['active_till_ko'] = True
    if 'party' in l_effect:
        effect['party'] = True
    try:
        percent_c = match[0]
        rounds = match[1] if len(match) > 1 else (1 if 'next' in l_effect else None)
        inc = 'increase' in l_effect
        if rounds is None and 'damage' in l_effect and effect.get('active_till_ko'):
            effect['active_rounds'] = -1
            effect['value'] = percent_c * (1 if inc else -1)
        else:
            effect['active_rounds'] = min(rounds, percent_c) if rounds else None
            effect['value'] = (max(rounds, percent_c) if rounds else percent_c) * (1 if inc else -1)
    except:
        pass
    if 'knock' in l_effect:
        effect['ko_against'] = 'gold' if 'gold' in l_effect else ('white' if 'white' in l_effect else 'all')
    effect['each'] = True if ' each ' in l_effect else False
    effect['unit'] = 'percent' if ('percent' in l_effect or '%' in l_effect) else 'flat'
    effect['target'] = 'opponent' if 'oppo' in l_effect or 'enemy' in l_effect else 'self'
    effect['move_type'] = ['white', 'gold'] if ('white' in l_effect and 'gold' in l_effect) else \
        (['gold'] if 'gold' in l_effect else
         (['blue'] if 'blue' in l_effect else
          (['miss'] if 'miss' in l_effect or 'red ' in l_effect else (
              ['purple'] if 'purple' in l_effect else (['white'] if 'white' in l_effect else ['white', 'gold'])))))
    if ('white' in effect['move_type'] or 'gold' in effect['move_type']) and effect['unit'] == 'percent':
        effect['select'] = 'lowest' if 'low' in l_effect else ('highest' if 'high' in l_effect else 'all')
        if effect['select'] != 'all':
            match effect['move_type']:
                case ['white'] | ['gold'] | ['purple']:
                    if effect['select'] == 'lowest':
                        effect['sorted_idx'] = 0
                    else:
                        effect['sorted_idx'] = 1
                # case :
                #     if effects['select'] == 'lowest':
                #         effects['sorted_idx'] = 2
                #     else:
                #         effects['sorted_idx'] = 3
                # case :
                #     if effects['select'] == 'lowest':
                #         effects['sorted_idx'] = 4
                #     else:
                #         effects['sorted_idx'] = 5
                case ['white', 'gold']:
                    if 'second' in l_effect:
                        if effect['select'] == 'lowest':
                            effect['sorted_idx'] = 1
                        else:
                            effect['sorted_idx'] = 2
                    else:
                        if effect['select'] == 'lowest':
                            effect['sorted_idx'] = 0
                        else:
                            effect['sorted_idx'] = 3
                case _:
                    effect['sorted_idx'] = None
    effect['type_id'] = str(get_unique_id(entries, effect))
    return effect
    # except:
    #     print(f'{l_effect}\n{traceback.format_exc()}')


def get_purple_move_effects(_id, stars):
    collection = db['PurpleEffectList']
    print(_id, stars)
    return collection.find_one({
        'purple_id': int(_id),
        'stars': int(stars),
    }, projection={'_id': 0})['effects']


def import_moves(col_name):
    with open('Zerpmon Moves - Move List POST PURPLE UPDATE 270824.csv', 'r') as csvfile:
        collection = db[col_name]
        print(collection.name)
        csvreader = csv.reader(csvfile)
        entries = []
        for row in csvreader:
            if row[1] == "" or row[0] == 'Move ID':
                continue
            # Insert the row data to MongoDB
            effects = {}
            row[5] = row[5].replace('White/Gold ', '')
            stars = None if row[3].isdigit() else len(row[3])
            if row[5] and row[6]:
                l_effect = row[5].lower()
                effects = get_purple_move_effects(row[6], stars)
                # get_effects(effects, entries, l_effect)
            # if col_name == 'MoveList':
            #     if 'turn' in row[5]:
            #         continue
            print(row)
            collection.update_one({'move_name': row[1]}, {'$set': {
                'move_id': row[0],
                'move_name': row[1],
                'type': row[2],
                'dmg': row[3],
                'stars': stars,
                'color': row[4].lower(),
                'notes': row[5],
                'purple_id': int(row[6]) if row[6] else None,
                'melee': int(row[7]) if row[7] and row[7].isdigit() else None,
                'effects': effects,
            }}, upsert=True)
        # collection.create_index({'move_name': 1})
        # collection.create_index({'move_id': 1})
        print(len(entries))


def import_purple_star_ids():
    with open('Zerpmon Moves - Purple Effect List 100924.csv', 'r') as csvfile:
        collection = db['PurpleEffectList']
        print(collection.name)
        collection.drop()
        csvreader = csv.reader(csvfile)
        entries = []
        for row in csvreader:
            if row[0] == 'Purple Move Effect ID':
                continue
            # Insert the row data to MongoDB
            effects = []
            effect_strings = []
            row.pop() # Buff/Debuff for now of no use
            stars = row.pop()
            purple_id = row.pop(0)
            print(purple_id)
            # filtered_rows = ['effect 1 string', 'effect 1 percent/value', ...']
            filtered_rows = [i for i in row if i and i != '-']
            if len(filtered_rows) < 2:
                continue
            print(filtered_rows)
            while len(filtered_rows) >= 2:
                disabled = filtered_rows[1].lower() == 'false'
                s1 = filtered_rows.pop(0).strip()
                s2 = filtered_rows.pop(0).strip()
                l_effect = f"{s1}{'' if s1.endswith('by') else ' by'} {s2 if s2.lower() not in ['false', 'true'] else f'({s2})'}"
                effects.append(get_effects(entries, l_effect.lower(), disabled =disabled ))
                effect_strings.append(l_effect)
            print(l_effect)

            collection.insert_one({
                'purple_id': int(purple_id),
                'stars': int(stars),
                'strings': effect_strings,
                'effects': effects,
            })
        print(len(entries))
        # collection.create_index({"purple_id": pymongo.ASCENDING})


def import_movesets():
    with open('Zerpmon Moves - Zerpmon Movesets 060924.csv', 'r') as csvfile:
        collection = db['MoveSets']
        movelist_col = db['MoveList2']
        # c2 = db['MoveSets2']
        # c2.drop()
        csvreader = csv.reader(csvfile)
        header = next(csvreader)  # Skip the header row
        print(header)
        header = [field.lower().split()[0] for field in header if field]
        print(header)

        for row in csvreader:
            # return
            # Remove empty fields from the row
            row = [field for field in row if field != "0.003083061299"]

            # if row[38] == "":
            #     continue

            # Insert the row data to MongoDB
            move_types = {row[6].lower().title(),
                          row[11].lower().title(),
                          row[16].lower().title(),
                          row[21].lower().title()}
            zType = [row[2].lower()] + ([row[3].lower()] if row[3] else [])
            zType = [(i if i != 'dragonling' else 'dragon') for i in zType]
            try:
                doc = {
                    'number': row[0],
                    'name': row[1],
                    'zerpmonType': zType,
                    # 'collection': row[2],
                    'moves': [
                        {'name': row[4], 'dmg': int(row[5]) if row[5] != "" else "", 'type': row[6], 'id': row[7],
                         'percent': float(row[8].replace("%", "")), 'color': header[3 + 1],
                         'melee': movelist_col.find_one({'move_name': row[4]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[9], 'dmg': int(row[10]) if row[10] != "" else "", 'type': row[11], 'id': row[12],
                         'percent': float(row[13].replace("%", "")), 'color': header[8 + 1],
                         'melee': movelist_col.find_one({'move_name': row[9]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[14], 'dmg': int(row[15]) if row[15] != "" else "", 'type': row[16], 'id': row[17],
                         'percent': float(row[18].replace("%", "")), 'color': header[13 + 1],
                         'melee': movelist_col.find_one({'move_name': row[14]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[19], 'dmg': int(row[20]) if row[20] != "" else "", 'type': row[21], 'id': row[22],
                         'percent': float(row[23].replace("%", "")), 'color': header[18 + 1],
                         'melee': movelist_col.find_one({'move_name': row[19]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[24], 'stars': len(row[25]), 'id': row[26],
                         'percent': float(row[27].replace("%", "")),
                         'color': header[23 + 1],
                         'melee': movelist_col.find_one({'move_name': row[24]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[28], 'stars': len(row[29]), 'id': row[30],
                         'percent': float(row[31].replace("%", "")),
                         'color': header[27 + 1],
                         'melee': movelist_col.find_one({'move_name': row[28]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': row[32], 'id': row[33], 'percent': float(row[34].replace("%", "")),
                         'color': header[31 + 1],
                         'melee': movelist_col.find_one({'move_name': row[32]}, {'_id': 0, 'melee': 1}).get('melee')},
                        {'name': 'Miss', 'id': row[36], 'percent': float(row[37].replace("%", "")),
                         'color': header[34 + 1],
                         'melee': movelist_col.find_one({'move_name': 'Miss'}, {'_id': 0, 'melee': 1}).get('melee')},
                    ],

                    'move_types': list(move_types),
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
                old_doc = collection.find_one_and_update({'name': row[1]}, {'$unset': {'moves': ''}})
                attr, img = None, None
                if old_doc.get('nft_id') is None or str(old_doc.get('nft_id')).startswith('trn-'):
                    trn_docs = list(collection.find({'name': {'$regex': row[1]}, 'nft_id': {'$regex': 'trn-'}}))
                    if len(trn_docs) > 0:
                        doc['isTRN'] = True
                        # Get all nfts with the same name and differing token_id
                        for trn_doc in trn_docs:
                            trn_doc['zerpmonType'] = doc['zerpmonType']
                            trn_doc['moves'] = doc['moves']
                            trn_doc['move_types'] = doc['move_types']
                            collection.update_one({'name': trn_doc['name']}, {'$set': trn_doc, })
                    with open("./newMetadata.json", "r") as f:
                        data = json.load(f)
                        print("null metadata found", data)
                        for obj in data:
                            print(obj['name'], row[1])
                            if obj['name'] == row[1]:
                                attr = obj['attributes']
                                img = obj['image']
                                # doc['attributes'] = obj['attributes']
                                # doc['image'] = obj['image']

                collection.update_one({'name': row[1]}, {'$set': doc, '$setOnInsert': {'attributes': attr,
                                                                                       'image': img,
                                                                                       'nft_id': row[38] if row[
                                                                                           38] else None
                                                                                       }}, upsert=True)
                print(row[1])
                # c2.insert_one(document=doc)
            except Exception as e:
                print(traceback.format_exc(), '\n', row)


# import_movesets()

def import_level():
    collection = db['levels']
    collection.drop()
    with open('Zerpmon_EXP_Scaling_for_Missions.csv', 'r') as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip the header row
        for row in reader:
            # Replace empty values with ""
            try:
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
            except:
                pass


def import_trainer_level():
    collection = db['levels_trainer']
    collection.drop()
    with open('XPScalingTrainers-040824.csv', 'r') as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip the header row
        for row in reader:
            # Replace empty values with ""
            try:
                row = ["" if x.strip() == "" else x for x in row]
                print(row)
                # Convert XP Required per level, Total XP Earned, Wins, Mission Refreshes and EXP Per Win to integers
                collection.insert_one({
                    'level': int(row[0]),
                    'xp_required': int(row[1]),
                    'total_xp': int(row[2]),
                    'wins_needed': float(row[3]),
                    'revive_potion_reward': 0 if row[4].strip() == "" else int(row[4]),
                    'mission_potion_reward': 0 if row[5].strip() == "" else int(row[5]),
                    'candy_frags': 0 if row[6].strip() == "" else int(row[6]),
                    'damage_buff': 0 if row[7].strip() == "" else float(row[7].replace('%', '')),
                    'white_percent_buff': 0 if row[8].strip() == "" else float(row[8].replace('%', '')),
                    'gold_percent_buff': 0 if row[9].strip() == "" else float(row[9].replace('%', '')),
                    'purple_percent_buff': 0 if row[10].strip() == "" else float(row[10].replace('%', '')),
                    'miss_percent_buff': 0 if row[11].strip() == "" else float(row[11].replace('%', '')),
                    'crit_percent_buff': 0 if row[12].strip() == "" else float(row[12].replace('%', '')),
                    'blue_percent_buff': 0 if row[13].strip() == "" else float(row[13].replace('%', '')),
                })
                collection.create_index({'level': 1})
            except:
                print(traceback.format_exc())


def import_trn_trainer_level():
    collection = db['levels_trainer_trn']
    collection.drop()
    with open('TRN Trainers Levelling.csv', 'r') as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip the header row
        for row in reader:
            # Replace empty values with ""
            try:
                row = ["" if x.strip() == "" else x for x in row]
                print(row)
                # Convert XP Required per level, Total XP Earned, Wins, Mission Refreshes and EXP Per Win to integers
                collection.insert_one({
                    'level': int(row[0]),
                    'xp_required': int(row[1]),
                    'total_xp': int(row[2]),
                    'wins_needed': float(row[3]),
                    'revive_potion_reward': 0 if row[4].strip() == "" else int(row[4]),
                    'mission_potion_reward': 0 if row[5].strip() == "" else int(row[5]),
                    'candy_frags': 0 if row[6].strip() == "" else int(row[6]),
                    'damage_buff': 0 if row[7].strip() == "" else float(row[7].replace('%', '')),
                    'miss_percent_buff': 0 if row[8].strip() == "" else float(row[8].replace('%', '')),
                    'apply_two_buffs': True
                })
                collection.create_index({'level': 1})
            except:
                print(traceback.format_exc())



def import_ascend_levels():
    collection = db['levels']
    t_xp = 7900
    s_xp = 750
    rewards = ['jawbreaker', 'star_candy', 'sour_candy', 'gummy_candy', 'overcharge_candy']
    temp_rewards = rewards.copy()
    gym_refills = 1
    cndy_cnt = 1
    r_m_potion = {31: 0, 32: 0, 33: 0, 34: 1, 35: 1, 36: 5, 37: 1, 38: 5, 39: 1, 40: 5, 41: 1, 42: 1, 43: 1, 44: 1,
                  45: 1, 46: 8,
                  47: 1, 48: 8, 49: 1, 50: 8, 51: 1, 52: 1, 53: 1, 54: 1, 55: 1, 56: 10, 57: 1, 58: 10, 59: 1, 60: 15}

    for i in range(31, 61):
        s_xp += 50
        t_xp += s_xp
        candy_slot, candy_frags = 0, 0
        reward = None, 0
        if len(temp_rewards) == 0:
            temp_rewards = rewards.copy()
            candy_slot, candy_frags = 1, 6
            gym_refills += 1
            if gym_refills == 3:
                cndy_cnt += 1
            elif gym_refills == 5:
                cndy_cnt += 1
        else:
            reward = temp_rewards.pop(), gym_refills
        print(i, t_xp, s_xp, reward, candy_slot, candy_frags)
        obj = {
            'level': i,
            'xp_required': s_xp,
            'total_xp': t_xp,
            'wins_needed': int(s_xp / 10),
            'revive_potion_reward': r_m_potion[i],
            'mission_potion_reward': r_m_potion[i],
            'candy_slot': candy_slot,
            'candy_frags': candy_frags
        }
        if reward[0]:
            obj['gym_refill_reward'] = reward[1]
            obj['extra_candy'] = reward[0]
            obj['extra_candy_cnt'] = cndy_cnt
        # collection.insert_one(obj)
        collection.update_one({'level': obj['level']}, {'$set': obj}, upsert=True)


def check_nft_cached(id, data):
    for i in data:
        if i['nftid'] == id:
            return True
    return False


def get_cached():
    with open("./metadata.json", "r") as f:
        return json.load(f)


# print(requests.get('https://bithomp.com/api/cors/v2/nft/0008138874D997D20619837CF3C7E1050A785E9F9AC53D7EEC38D87C048F1DE1?uri=true&metadata=true').text)
def import_attrs_img():
    data = get_all_z()
    # tba = get_cached()  # [{nftid, metadata, uri},...]
    for i in data:
        if i['nft_id'] is None:
            continue
        id = i['nft_id']
        if i.get('image') and i.get('attributes'):
            continue
        chain = 'xahau' if i.get('chain', '') == 'xahau' else 'xrpl'
        match chain:
            case 'xrpl':
                path = 'https://bithomp.com/api/v2/nft/'
            case 'xahau':
                path = 'https://xahauexplorer.com/api/cors/v2/nft/'
            case _:
                path = 'https://bithomp.com/api/cors/v2/nft/'
        rr2 = requests.get(
            path + f"{id}?uri=true&metadata=true", headers={"x-bithomp-token": "76c6dd73-50e1-4b20-847f-75926ae48cef"})
        res = rr2.json()
        print(i, res, id)
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
        if i.get('attributes'):
            for _i, j in enumerate(i.get('attributes')):
                if j['trait_type'] == 'Type':
                    i['attributes'][_i]['value'] = str(j['value']).lower().title()
                    r = zerpmon_collection.find_one_and_update({'name': i['name']},
                                                               {'$set': {'attributes': i['attributes']}})
                    print(r)
        if 'omni' in i.get('zerpmonType', []):
            r = zerpmon_collection.update_one({'name': i['name']},
                                              {'$set': {'isOmni': True}})


def save_30_level_zerp():
    zerpmon_collection = db['MoveSets2']
    print(zerpmon_collection.count_documents({}))
    c2 = db['MoveSets3']
    c2.drop()
    for document in zerpmon_collection.find({}, {'_id': 0, 'z_flair': 0, 'white_candy': 0, 'gold_candy': 0,
                                                 'level': 0, 'maxed_out': 0, 'xp': 0, 'licorice': 0, 'total': 0,
                                                 'winrate': 0, 'ascended': 0, 'punished': 0}):
        if document['nft_id']:
            document['level'] = 30
            print(document['name'])
            miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
            percent_change = 10
            percent_change = percent_change if percent_change < miss_percent else miss_percent
            count = len([i for i in document['moves'] if i['name'] != "" and i['color'] != "blue"]) - 1
            # print(document)
            for i, move in enumerate(document['moves']):
                if move['color'] == 'miss':
                    move['percent'] = round(float(move['percent']) - percent_change, 2)
                    document['moves'][i] = move
                elif move['name'] != "" and float(move['percent']) > 0 and move['color'] != "blue":
                    move['percent'] = round(float(move['percent']) + (percent_change / count), 2)
                    document['moves'][i] = move

            c2.insert_one(document)


def save_30_level_trainer():
    trainer_collection = db['trainers']
    print(trainer_collection.count_documents({}))
    c2 = db['trainers3']
    c2.drop()
    for document in trainer_collection.find({}):
        if not (document.get('isCollab') or str(document['name']).startswith('Shill')):
            document['trainer_level'] = 30
            document['trainer_xp'] = 0
            print(document['name'])
            document['buff_selected'] = random.choice(config_extra.trainer_buff_list)
        # print(document)
        c2.insert_one(document)


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
    for document in db['MoveSets'].find({'nft_id': {'$ne': None}}):
        del document['_id']
        if document['image'] is None:
            continue
        if 'level' in document and document['level'] / 10 >= 1:
            if document['level'] > 30:
                if int(document.get('number', 0)) < 100000:
                    if 'Dragon' in [i['value'] for i in document['attributes'] if
                                    i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']:
                        pass
                    else:
                        lvl = document['level'] - 30
                        percent_change = 6 * (lvl // 10)
                        for i, move in enumerate(document['moves']):
                            if move['color'] == 'blue':
                                move['percent'] = move['percent'] + percent_change
                                document['moves'][i] = move
            if document['level'] >= 10:
                document['level'] = min(30, document['level'])
                print(document['name'])
                miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
                percent_change = 3.33 * (document['level'] // 10)
                if percent_change == 9.99:
                    percent_change = 10
                percent_change = percent_change if percent_change < miss_percent else miss_percent
                count = len([i for i in document['moves'] if i['name'] != "" and i['color'] != "blue"]) - 1
                print(document)
                for i, move in enumerate(document['moves']):
                    if move['color'] == 'miss':
                        move['percent'] = round(float(move['percent']) - percent_change, 2)
                        document['moves'][i] = move
                    elif move['name'] != "" and float(move['percent']) > 0 and move['color'] != "blue":
                        move['percent'] = round(float(move['percent']) + (percent_change / count), 2)
                        document['moves'][i] = move
            save_new_zerpmon({'moves': document['moves'], 'name': document['name']})
        w_candy = document.get('white_candy', 0)
        g_candy = document.get('gold_candy', 0)
        p_candy = document.get('purple_candy', 0)
        if w_candy > 0:

            original_zerp = db['MoveSets2'].find_one({'name': str(document['name']).split(' #')[0]})

            for i, move in enumerate(document['moves']):
                if move['color'].lower() == 'white':
                    document['moves'][i]['dmg'] = round(
                        document['moves'][i]['dmg'] + (original_zerp['moves'][i]['dmg'] * 0.02 * w_candy),
                        1)
            # save_new_zerpmon({'moves': document['moves'], 'name': document['name']})
        if g_candy > 0:
            original_zerp = db['MoveSets2'].find_one({'name': str(document['name']).split(' #')[0]})
            for i, move in enumerate(document['moves']):
                if move['color'].lower() == 'gold':
                    document['moves'][i]['dmg'] = round(
                        document['moves'][i]['dmg'] + original_zerp['moves'][i]['dmg'] * 0.02 * g_candy,
                        1)
        if p_candy >= 10:
            for i, move in enumerate(document['moves']):
                if move['color'].lower() == 'purple':
                    document['moves'][i]['stars'] += 1
        save_new_zerpmon({'moves': document['moves'], 'name': document['name']})

"""Old"""
def get_issuer_nfts_data(issuer, marker_provided=None):
    i = 1
    try:
        ti = time.time()
        print("get_collection_5kk")
        marker = True if marker_provided else False
        markerVal = marker_provided if marker_provided else None
        url = f"https://bithomp.com/api/v2/nfts?issuer={issuer}&limit=100" if not marker else \
            f"https://bithomp.com/api/v2/nfts?issuer={issuer}&marker={markerVal}&limit=100"
        response = requests.get(url, headers={"x-bithomp-token": "76c6dd73-50e1-4b20-847f-75926ae48cef"})
        # print(response.text)
        response = response.json()
        print(response, url)
        nfts = response['nfts']
        print('nfts len:', len(nfts))
        if 'marker' in response:
            marker = True
            markerVal = response['marker']

        while marker:
            i += 1
            if i >= 10:
                time.sleep(60)
                i = 1
            url2 = f"https://bithomp.com/api/v2/nfts?issuer={issuer}&marker={markerVal}&limit=100"
            response2 = requests.get(url2, headers={"x-bithomp-token": "76c6dd73-50e1-4b20-847f-75926ae48cef"})
            response2 = response2.json()
            try:
                nfts2 = response2['nfts']
                nfts.extend(nfts2)
                print(markerVal)
                if 'marker' in response2:
                    marker = True
                    markerVal = response2['marker']
                else:
                    marker = False
            except:
                print(traceback.format_exc(), '\n\n', response2)
                break
        print("Total XRPL NFTs: ", len(nfts), marker)

        # Grab Xahau nfts as well
        # print("get_collection_xahau")
        # url = f"https://xahauexplorer.com/api/cors/v2/uritokens?list=uritokens&issuer={issuer}&limit=400"
        # response = requests.get(url)
        # # print(response.text)
        # response = response.json()
        #
        # x_nfts = response['uritokens']
        # marker = False
        # markerVal = ''
        # if 'marker' in response:
        #     marker = True
        #     markerVal = response['marker']
        #
        # while marker:
        #     url2 = f"https://xahauexplorer.com/api/cors/v2/uritokens?list=uritokens&issuer={issuer}&marker={markerVal}&limit=400"
        #     response2 = requests.get(url2)
        #     response2 = response2.json()
        #
        #     nfts2 = response2['uritokens']
        #     x_nfts.extend(nfts2)
        #
        #     if 'marker' in response2:
        #         marker = True
        #         markerVal = response2['marker']
        #     else:
        #         marker = False
        # print("Total XAHAU NFTs: ", len(x_nfts))
        # for item in x_nfts:
        #     item['nftokenID'] = item['uriTokenID']
        # nfts.extend(x_nfts)
        time.sleep(max(1, 10 - (time.time() - ti)))
        return nfts
    except Exception as e:
        print(traceback.format_exc())
        exit()


async def cache_data(get_eqs=True, get_collab=True):
    try:
        """Clio call instead of Bithomp"""
        z_nfts = await fetchNFTsByIssuer('rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME')
        z_nfts = [i for i in z_nfts if not i.get('is_burned')]
        print(f"Nfts after filtering burned ones: {len(z_nfts)}")
        """
        z_nfts item eg
        {
            "nft_id": "0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E0000099B00000000",
            "ledger_index": 76485968,
            "owner": "rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME",
            "is_burned": true,
            "uri": "697066733A2F2F516D62664E6275645675434D3838554E743863547876724D7147415666414662464B586F5838477A47776B756D322F312E6A736F6E",
            "flags": 8,
            "transfer_fee": 5000,
            "issuer": "rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME",
            "nft_taxon": 0,
            "nft_serial": 0
        }
        """
        # time.sleep(60)
        # nfts = get_issuer_nfts_data('rXuRpzTATAm3BNzWNRLmzGwkwJDrHy6Jy', marker_provided=None)

        """Update trainers col"""

        # for nft in nfts:
        #     obj = {'nft_id': nft['nftokenID'], 'image': nft['metadata']['image'], 'name': nft['metadata']['name']}
        #
        #     for key in nft['metadata']['attributes']:
        #         key, val = key['trait_type'], key['value']
        #         obj[key.lower()] = val
        #     db['trainers'].update_one({'nft_id': obj['nft_id']}, {'$setOnInsert': obj}, upsert=True)
        #     print(obj)
        #

        # if get_eqs:
        #     e_nfts = get_issuer_nfts_data('rEQQ8tTnJm4ECbPv71K9syrHrTJTv6DX3T')
        # else:
        #     e_nfts = []

        """Collab equipment update"""

        # if get_collab:
        #     c_nfts = get_collab_nfts()
        #     for nft in c_nfts:
        #         obj = {'nft_id': nft['nftokenID'], 'image': nft['metadata']['image'], 'name': nft['metadata']['name']}
        #
        #         for key in nft['metadata']['attributes']:
        #             key, val = key['trait_type'], key['value']
        #             obj[key.lower()] = val
        #         db['trainers'].update_one({'nft_id': obj['nft_id']}, {'$setOnInsert': obj}, upsert=True)
        #         print(obj)
        # else:
        #     c_nfts = []

        """Only needs to run occasionally"""
        # z_nfts.extend(nfts)
        # z_nfts.extend(e_nfts)
        # z_nfts.extend(c_nfts)
        tba = get_cached()
        new_metadata_updates = 0
        for nft in z_nfts:
            if nft['uri'] not in tba:
                """Fetch metadata here using http req"""
                uri = hex_to_str(nft['uri'])
                url = uri if "https:/" in uri else config_extra.ipfsGateway + uri.replace("ipfs://", "")
                print(url)
                metadata = requests.get(url).json()
                print(metadata)
                for _i, j in enumerate(metadata['attributes']):
                    if j['trait_type'] == 'Type':
                        metadata['attributes'][_i]['value'] = str(j['value']).strip().lower().title()
                meta = {
                    'nftid': nft['nft_id'],
                    'metadata': metadata,
                    'uri': nft['uri']
                }

                tba[nft['uri']] = meta
                db['nft-uri-cache'].update_one({'nftid': meta['nftid']},
                                               {'$set': meta}, upsert=True)
                new_metadata_updates += 1
        print(f"Updated {new_metadata_updates} docs with new metadata")
        with open("./metadata.json", "w") as f:
            json.dump(tba, f)

        collection = db['MoveSets']
        for nft in collection.find({}, {'_id': 0, 'z_flair': 0, 'white_candy': 0, 'gold_candy': 0,
                                        'level': 0, 'maxed_out': 0, 'xp': 0, 'licorice': 0, 'total': 0, 'winrate': 0,
                                        'ascended': 0, 'punished': 0}):
            if nft.get('isTRN') or str(nft.get('nft_id')).startswith('trn-'):
                continue
            if nft.get('nft_id') is None or nft['image'] is None:
                found = db['nft-uri-cache'].find_one({'metadata.name': nft['name']})
                if found:
                    nft['nft_id'] = found['nftid']
                    attrs = found['metadata']['attributes']
                    image = found['metadata']['image']
                    nft['attributes'] = attrs
                    nft['image'] = image
                    db['MoveSets'].update_one({'name': nft['name']}, {
                        '$set': {'nft_id': found['nftid'], 'attributes': attrs, 'image': image}}, upsert=True)
                    print('found:', nft['name'])
                else:
                    continue
                # collection.update_one({'name': nft['name']}, {'$set': {'nft_id': found['nftid']}})

            db['MoveSets2'].update_one({'name': nft['name']}, {'$set': nft}, upsert=True)

    except Exception as e:
        print(traceback.format_exc(), ' error')


def get_collab_nfts():
    with open('./ZerpmonCollabTrainerNFTs.txt', 'r') as file:
        tokenIds = [i.strip('\n') for i in file.readlines()]
        # print(tokenIds)
        data = get_issuer_nfts_data(config.ISSUER['TrainerV2'])
        nfts = [i for i in data if i['nftokenID'] in tokenIds]
        print([i['nftSerial'] for i in nfts])
        return nfts


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


def import_equipments(col_name):
    with open('Zerpmon Moves - Equipment 150924.csv', 'r') as csvfile:
        collection = db[col_name]
        # collection.drop()
        csvreader = csv.reader(csvfile)
        unique_types = set()
        for row in csvreader:
            if row[1] == "":
                continue
            notes = [f"{row[1]} {row[2]}", (f"{row[3]} {row[4]}" if row[3] else None)]
            effect_list = []
            for note in notes:
                if note:
                    note = note.lower()
                    note = note.replace(" and ", "@")
                    separated_note = note.split("@")
                    for s in separated_note:
                        print(s)
                        if 'increase effects are' in s:
                            change = 'multiplier'
                        else:
                            change = 'decrease' if ('decrease' in s) else ('set' if ('change' in s) else 'increase')
                        change_val_type = 'percent' if 'halved' in s or 'double' in s or 'quartered' in s else 'flat'
                        s = s.replace('halved', '50% less')
                        s = s.replace('quartered', '75% less')
                        s = s.replace('double', '100%')
                        nums = extract_numbers(s)
                        p_val = abs(nums[-1])
                        change_val = None if len(nums) < 2 else (-1 if 'less' in s or 'weaker' in s else 1) * abs(
                            nums[0])

                        unit = ('percent-chance' if 'chance' in s else 'percent') if '%' in s else 'flat'
                        target = 'opponent' if ('oppo' in s and 'by oppo' not in s) or 'enemy' in s else 'self'
                        e_type = ''
                        if True:
                            if 'come back' in s:
                                e_type = 'survive-chance'
                            elif 'pierce' in s:
                                e_type = f'pierce-{change}'
                            elif 'crit' in s:
                                if 'crit chance to' in s:
                                    e_type = 'crit-set'
                                else:
                                    e_type = 'crit-chance'
                                    p_val *= 1 if change == 'increase' else -1
                            elif 'purple star' in s or 'purple move star' in s or ('purple' in s and 'weaker' in s):
                                if 'chance' in s:
                                    e_type = f'purple-buff-chance'
                                else:
                                    p_val *= 1 if change == 'increase' else -1
                                    e_type = f'purple-stars-increase'
                            elif 'roll again' in s or 'reroll' in s:
                                e_type = 'reroll-on-miss'
                            elif 'miss' in s:
                                if 'remove own miss upon own miss' in s:
                                    e_type = f'remove-miss-on-miss'
                                else:
                                    e_type = f'miss-{change}'
                            elif 'white attacks into gold attacks' in s:
                                e_type = f'white-to-gold-chance'
                            elif 'damage' in s and '0 damage' not in s:
                                color = ''
                                if 'gold' in s:
                                    color = 'gold-'
                                elif 'white' in s:
                                    color = 'white-'
                                if 'chance' in s:
                                    if color == '':
                                        color = 'damage-'
                                    e_type = f'{color}buff-chance'
                                else:
                                    e_type = f'{color}damage-{change}'
                            elif 'blue chance' in s or 'blue move chance' in s:
                                e_type = f'blue-{change}'
                            elif '0 damage' in s:
                                if 'omni' in s:
                                    e_type = f'omni-to-zero'
                                elif 'gold' in s:
                                    e_type = f'gold-to-zero'
                                else:
                                    e_type = f'white-to-zero'
                            elif 'immuni' in s:
                                e_type = 'immunity'
                            elif 'favour' in s:
                                e_type = 'favoured-chance'
                            elif 'random equipment' in s:
                                e_type = 'random-equipment'
                            else:
                                s = ' '.join(separated_note)
                                if 'gold' in s and 'chance' in s:
                                    e_type = f'gold-percent-{change}'
                                elif 'white' in s and 'chance' in s:
                                    e_type = f'white-percent-{change}'
                                elif 'purple' in s and 'chance' in s:
                                    e_type = f'purple-percent-{change}'
                        effect_list.append({
                            "type": e_type,
                            "value": p_val,
                            "unit": unit,
                            "target": target,
                            "specifics": {
                                "type": change_val_type,
                                "value": change_val
                            }
                        })
                        unique_types.add(e_type)
                        print(e_type)
            # Insert the row data to MongoDB
            last_v = row.pop()
            if last_v == 'true':
                print(notes)
                notes = [n.split('100')[0].strip() for n in notes if n]
            name = row.pop() if last_v == 'true' else last_v
            collection.update_one({'name': name}, {'$set': {
                'type': row[0].lower().title(),
                'name': name,
                'notes': [n for n in notes if n],
                "effects": effect_list,
                "pickRandomEq": len([i for i in effect_list if i['type'] == 'random-equipment']) > 0
            }}, upsert=True)
        print(unique_types)


def switch_cached():
    with open("./metadata.json", "r") as f:
        arr = json.load(f)
        new_t = {}
        uris = []
        for i in arr:
            if i['uri'] not in uris:
                uris.append(i['uri'])
                new_t[i['uri']] = i
        print(new_t, len(new_t))
        with open("./metadata.json", "w") as fw:
            json.dump(new_t, fw, indent=2)


def gift_ascension_reward():
    users_c = db['users']
    collection = db['MoveSets']
    for user in users_c.find():
        reward_c = 0
        if len(user.get('zerpmons', [])) > 0:
            for idx, zerp in user['zerpmons'].items():
                zerp_obj = collection.find_one({'name': zerp['name']})
                if zerp_obj.get('ascended'):
                    reward_c += 10
                    # print(zerp['name'], zerp_obj['level'])
            if reward_c > 0:
                print(user['username'], 'revive_potion:', reward_c, 'mission_potion:', reward_c)
                users_c.update_one({'address': user['address']},
                                   {'$inc': {'revive_potion': reward_c, 'mission_potion': reward_c}})


def clear_slot_reward():
    users_c = db['users']
    collection = db['MoveSets']
    for user in users_c.find():
        candy_white, candy_gold = 0, 0
        if len(user.get('zerpmons', [])) > 0:
            for idx, zerp in user['zerpmons'].items():
                zerp_obj = collection.find_one({'name': zerp['name']})
                if zerp_obj.get('level', 0) < 36 and 'extra_candy_slot' in zerp_obj:
                    candy_w = max(0, zerp_obj.get('white_candy', 0) - 5)
                    candy_g = max(0, zerp_obj.get('gold_candy', 0) - 5)
                    candy_gold += candy_g
                    candy_white += candy_w
                    print(zerp['name'], zerp_obj['level'])
                    collection.update_one({'name': zerp['name']},
                                          {'$inc': {'white_candy': -candy_w, 'gold_candy': -candy_g},
                                           '$unset': {'extra_candy_slot': ''}})
            if candy_white + candy_gold > 0:
                print(user['username'], 'white_candy:', candy_white, 'gold_candy:', candy_gold)
                users_c.update_one({'address': user['address']},
                                   {'$inc': {'white_candy': candy_white, 'gold_candy': candy_gold}})


def add_gym_level_buffs():
    gym_level_c = db['gym_buffs']
    gym_dmg_buff = {1: 0, 2: 0, 3: 0, 4: 10, 5: 20, 6: 30, 7: 30, 8: 40, 9: 50, 10: 60,
                    11: 60, 12: 70, 13: 70, 14: 80, 15: 90, 16: 100, 17: 100, 18: 100, 19: 100, 20: 125}
    for i in range(20):
        stage = i + 1
        buff_obj = {
            'stage': stage,
            'zerpmonLevel': 1 if stage == 1 else (15 if stage == 2 else 30),
            'dmgBuffPercent': gym_dmg_buff[stage],
            'trainerBuff': True if stage > 12 else False,
            'critBuffPercent': 25 if stage == 17 else (50 if stage == 18 else (70 if stage in [19, 20] else 0)),
            'equipment1': 'gymType' if stage > 6 else None,
            'equipment2': 'Tattered Cloak' if stage > 10 else None
        }
        gym_level_c.update_one({
            'stage': stage
        }, {'$set': buff_obj}, upsert=True
        )


def add_gym_trainers():
    gym_c = db['gym_zerp']
    for type_, leader in config.LEADER_NAMES.items():
        gym_c.update_one({
            'name': type_ + ' Gym Leader'
        }, {'$set': {
            'trainer': {
                "nft_id": '',
                "image": '',
                "name": leader,
                "type": type_
            }
        }}, upsert=True
        )


# gift_ascension_reward()
# switch_cached()
# import_boxes()


# import_level()
# import_ascend_levels()
# gift_ascension_reward()

# import_equipments('Equipment')
# import_equipments('Equipment2')

# add_gym_level_buffs()
# add_gym_trainers()
# import_trainer_level()
# import_purple_star_ids()
# import_moves('MoveList')
# import_moves('MoveList2')
# import_movesets()
# #import_attrs_img()
# asyncio.run(cache_data(get_eqs=False, get_collab=False))
# clean_attrs()
# update_all_zerp_moves()
# save_30_level_zerp()

# import_trn_trainer_level()
# save_30_level_trainer()
# r = asyncio.run(fetchNFTsByIssuer('rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME', 100))
# print(json.dumps(r[0], indent=4))