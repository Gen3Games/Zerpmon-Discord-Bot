import asyncio
import datetime
import json
import logging
import random
import re
import sys
import time
import traceback
import uuid
from xrpl.utils import parse_nftoken_id

from utils import battle_effect
import pymongo
import pytz
from pymongo import MongoClient, ReturnDocument, DESCENDING, UpdateOne
import config
import config_extra
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorChangeStream

client = AsyncIOMotorClient(config.MONGO_URL)
db = client['Zerpmon']

# Instantiate Static collections

move_collection = db['MoveList']
level_collection = db['levels']
equipment_col = db['Equipment']

Address_to_dest_tag_mapping = {}


async def get_destination_tag(address, db_sep= None):
    if Address_to_dest_tag_mapping.get(address) is None:
        users_collection = db['users'] if db_sep is None else db_sep['users']
        res = await users_collection.find_one({'address': address}, projection={'_id': 0, 'destination_tag': 1})
        Address_to_dest_tag_mapping[address] = res.get('destination_tag') if res else None
    return Address_to_dest_tag_mapping[address]


async def get_destination_tag_from_id(discord_id):
    users_collection = db['users']
    res = await users_collection.find_one({'discord_id': f"{discord_id}"}, projection={'_id': 0, 'destination_tag': 1})
    return res.get('destination_tag') if res else None


async def get_next_ts(days=1):
    # Get the current time in UTC
    current_time = datetime.datetime.now(pytz.utc)

    # Calculate the time difference until the next UTC 00:00
    next_day = current_time + datetime.timedelta(days=days)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    return target_time.timestamp()


async def is_monday():
    current_time = datetime.datetime.now(pytz.utc)
    return current_time.weekday() == 0


async def update_address(new_addr, old_addr):
    users_collection = db['users']
    res = await users_collection.update_one({'address': old_addr}, {'$set': {'address': new_addr}})
    return res.acknowledged


async def save_user(user):
    users_collection = db['users']
    # Upsert user
    # print(user)

    doc_str = json.dumps(user)
    user = json.loads(doc_str)
    print(user)
    result = await users_collection.update_one(
        {'address': user['address']},
        {'$set': user},
        upsert=True
    )

    if result.upserted_id:
        print(f"Created new user with id {result.upserted_id}")
    else:
        print(f"Updated user")


async def update_user_decks(user_obj, discord_id, serials, t_serial, e_serial, remove_serials, address=None):
    # if len(remove_serials['zerpmons']) + len(remove_serials['trainer_cards']) + len(remove_serials['equipments']) == 0:
    #     logging.error(f"{user_obj['address']} \nNONE")
    #     return
    if address:
        user_obj = await get_user(address)
    else:
        user_obj = await get_owned(discord_id)

    if serials is None and t_serial is None and e_serial is None:
        serials = list(user_obj['zerpmons'].keys())
        print(serials, remove_serials)
        if len(remove_serials['zerpmons']) > 0:
            serials.remove(remove_serials['zerpmons'][0])
        t_serial = list(user_obj['trainer_cards'].keys())
        if len(remove_serials['trainer_cards']) > 0:
            t_serial.remove(remove_serials['trainer_cards'][0])
        e_serial = list(user_obj['equipments'].keys())
        if len(remove_serials['equipments']) > 0:
            e_serial.remove(remove_serials['equipments'][0])
        print(t_serial, e_serial)
    mission_deck = user_obj["mission_deck"] if 'mission_deck' in user_obj else {}
    battle_deck = user_obj["battle_deck"] if 'battle_deck' in user_obj else {'0': {}, '1': {}, '2': {}, '3': {},
                                                                             '4': {}}
    br_deck = user_obj["br_champion_decks"] if 'br_champion_decks' in user_obj else {}
    gym_deck = user_obj["gym_deck"] if 'gym_deck' in user_obj else {}

    kickedCards = {
        'battle': set(),
        'gym': set(),
        'mission': set(),
        'br': set(),
    }
    unset_query = {
        **{f"zerpmons.{i}": '' for i in remove_serials['zerpmons']},
        **{f"trainer_cards.{i}": '' for i in remove_serials['trainer_cards']},
        **{f"equipments.{i}": '' for i in remove_serials['equipments']},
    }
    set_query = {}

    for k, v in mission_deck.items():
        if v and v not in serials:
            set_query[f'mission_deck.{k}'] = None
            kickedCards['mission'].add(user_obj['zerpmons'].get(v, {}).get('name'))

    for k, v in battle_deck.items():
        for serial in v:
            if serial == "trainer":
                if v[serial] and v[serial] not in t_serial:
                    set_query[f'battle_deck.{k}.trainer'] = None
                    kickedCards['battle'].add(user_obj['trainer_cards'].get(v[serial], {}).get('name'))
            elif v[serial] and v[serial] not in serials:
                set_query[f'battle_deck.{k}.{serial}'] = None
                kickedCards['battle'].add(user_obj['zerpmons'].get(v[serial], {}).get('name'))

    for k, v in gym_deck.items():
        for serial in v:
            if serial == "trainer":
                if v[serial] and v[serial] not in t_serial:
                    set_query[f'gym_deck.{k}.{serial}'] = None
                    kickedCards['gym'].add(user_obj['trainer_cards'].get(v[serial], {}).get('name'))
            elif v[serial] and v[serial] not in serials:
                set_query[f'gym_deck.{k}.{serial}'] = None
                kickedCards['gym'].add(user_obj['zerpmons'].get(v[serial], {}).get('name'))
    for i in range(20):
        sr = str(i)
        if br_deck.get(sr):
            b_deck = br_deck.get(sr)
            br_t, br_z, br_e = b_deck.get('trainer'), b_deck.get('zerpmon'), b_deck.get('equipment')
            if br_t and br_t not in t_serial:
                set_query[f'br_champion_decks.{sr}.trainer'] = None
                kickedCards['br'].add(user_obj['trainer_cards'].get(br_t, {}).get('name'))
            if br_e and br_e not in e_serial:
                set_query[f'br_champion_decks.{sr}.equipment'] = None
                kickedCards['br'].add(user_obj['equipments'].get(br_e, {}).get('name'))
            if br_z and br_z not in serials:
                set_query[f'br_champion_decks.{sr}.zerpmon'] = None
                kickedCards['br'].add(user_obj['zerpmons'].get(br_z, {}).get('name'))
        else:
            break
    for deck in ['recent_deck', 'recent_deck1', 'recent_deck5']:
        if user_obj.get(deck):
            try:
                for sr, val in user_obj.get(deck, {}):
                    if sr == 'trainer' and val not in t_serial:
                        unset_query[deck] = ""
                        break
                    elif val not in serials:
                        unset_query[deck] = ""
                        break
            except:
                pass

    """Clear PvP decks here"""
    if user_obj.get('pvp_decks'):
        for deck in ['1', '3', '5']:
            print('here')
            if user_obj['pvp_decks'].get(deck, {}).get('z'):
                try:
                    for sr, val in user_obj['pvp_decks'][deck]['z'].items():
                        if sr == 'trainer':
                            if val not in t_serial:
                                set_query[f'pvp_decks.{deck}.z'] = {}
                                set_query[f'pvp_decks.{deck}.valid'] = False
                                break
                        elif val not in serials:
                            set_query[f'pvp_decks.{deck}.z'] = {}
                            set_query[f'pvp_decks.{deck}.valid'] = False
                            break
                except:
                    pass
            for extra_deck in ['deck2', 'deck3']:
                try:
                    for sr, val in user_obj['pvp_decks'][deck][extra_deck]['z'].items():
                        if sr == 'trainer':
                            if val not in t_serial:
                                set_query[f'pvp_decks.{deck}.{extra_deck}.z'] = {}
                                set_query[f'pvp_decks.{deck}.{extra_deck}.valid'] = False
                                break
                        elif val not in serials:
                            set_query[f'pvp_decks.{deck}.{extra_deck}.z'] = {}
                            set_query[f'pvp_decks.{deck}.{extra_deck}.valid'] = False
                            break
                except:
                    pass

    logging.error(f"{user_obj['address']} \n"
                  f"Set Query {set_query} \n"
                  f"Unset Query: {unset_query}\n"
                  f"Remove Serials: {remove_serials}")
    if len(set_query) + len(unset_query) == 0:
        logging.error(f"{user_obj['address']} \nNONE")
        return
    # Send push notification here
    await db['users'].update_one(
        {'discord_id': user_obj["discord_id"], 'address': user_obj['address']},
        {'$set': {**set_query}, '$unset': {**unset_query}},
        upsert=True
    )
    notifications = []
    for k, v in kickedCards.items():
        values = [i for i in v if i]
        if len(values) > 0:
            notifications.append(
                {
                    'title': f"Cards removed from {k.upper()} deck",
                    'body': ', '.join(values),
                    'url': '',
                }
            )
    # print(notifications)
    if len(notifications) > 0:
        await send_user_notification(
            notifications,
            user_obj['address'],
            str(user_obj['_id'])
        )


async def remove_user_nft_addr(address, serial, trainer=False, equipment=False, db_sep=None):
    remove_srs = {
        'zerpmons': [],
        'trainer_cards': [],
        'equipments': [],
    }
    if equipment:
        remove_srs['equipments'] = [serial]
    elif trainer:
        remove_srs['trainer_cards'] = [serial]
    else:
        remove_srs['zerpmons'] = [serial]
    await update_user_decks({}, '', None, None, None, remove_srs, address)


async def remove_user_nft(discord_id, serial, trainer=False, equipment=False, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']
    # Upsert user
    # print(user)
    user_obj = await get_owned(str(discord_id))
    update_query = {"$unset": {f"equipments.{serial}": ""}} if equipment else (
        {"$unset": {f"zerpmons.{serial}": ""}} if not trainer else {"$unset": {f"trainer_cards.{serial}": ""}})
    # if not trainer and not equipment:
    #     for deck in ['recent_deck', 'recent_deck1', 'recent_deck5']:
    #         if serial in list(user_obj.get(deck, {}).values()):
    #             update_query["$unset"][deck] = ""

    result = await users_collection.update_one(
        {'discord_id': discord_id},
        update_query
    )


async def add_user_nft(address, serial, zerpmon, trainer=False, equipment=False, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']
    # Upsert user
    # print(user)

    doc_str = json.dumps(zerpmon)
    zerpmon = json.loads(doc_str)
    # print(zerpmon)
    update_query = {"$set": {f"equipments.{serial}": zerpmon}} if equipment else (
        {"$set": {f"zerpmons.{serial}": zerpmon}} if not trainer else
        {"$set": {f"trainer_cards.{serial}": zerpmon}})
    await users_collection.update_one(
        {'address': address},
        update_query
    )


async def save_new_zerpmon(zerpmon):
    zerpmon_collection = db['MoveSets']
    print(zerpmon)

    doc_str = json.dumps(zerpmon)
    zerpmon = json.loads(doc_str)

    result = await zerpmon_collection.update_one(
        {'name': zerpmon['name']},
        {'$set': zerpmon},
        upsert=True)

    if result.upserted_id:
        print(f"Created new Zerpmon with id {result.upserted_id}")
        return f"Successfully added a new Zerpmon {zerpmon['name']}"
    else:
        print(f"Updated Zerpmon with name {zerpmon['name']}")
        return f"Successfully updated Zerpmon {zerpmon['name']}"


async def get_all_users_cursor():
    users_collection = db['users']

    result = users_collection.find()

    return result


async def get_all_users(field='gym'):
    users_collection = db['users']

    result = await users_collection.find({}, projection={'_id': 0, 'address': 1, 'discord_id': 1, 'gym': 1}).to_list(None)
    return [i for i in result]


async def get_owned(user_id, autoc=False, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']
    user_id = str(user_id)
    if not autoc:
        result = await users_collection.find_one({"discord_id": user_id})
    else:
        pipeline = [{'$match': {'discord_id': user_id}},
                    {
                        '$project': {
                            '_id': 0,
                            'zerpmons': {
                                '$map': {
                                    'input': {'$objectToArray': '$zerpmons'},
                                    'as': 'zerpmon',
                                    'in': {
                                        'sr': '$$zerpmon.k',
                                        'name': '$$zerpmon.v.name',
                                        'attributes': '$$zerpmon.v.attributes'
                                    }
                                }
                            },
                            'trainer_cards': {
                                '$map': {
                                    'input': {'$objectToArray': '$trainer_cards'},
                                    'as': 'trainer',
                                    'in': {
                                        'sr': '$$trainer.k',
                                        'name': '$$trainer.v.name',
                                        'attributes': '$$trainer.v.attributes'
                                    }
                                }
                            },
                            'equipments': {
                                '$map': {
                                    'input': {'$objectToArray': '$equipments'},
                                    'as': 'equipment',
                                    'in': {
                                        'sr': '$$equipment.k',
                                        'name': '$$equipment.v.name',
                                        'attributes': '$$equipment.v.attributes'
                                    }
                                }
                            }
                        }
                    }
                    ]
        res = list(await users_collection.aggregate(pipeline).to_list(None))[0]
        print(len(res['zerpmons']), res['trainer_cards'])
        for key in ['zerpmons', 'trainer_cards', 'equipments']:
            for idx in range(len(res[key])):
                i = res[key][idx]
                res[key][idx] = {'name': i['name'],
                                 'type': [_i['value'] for _i in i['attributes'] if
                                          _i['trait_type'] in ['Type', 'Affinity']],
                                 'sr': i['sr']}

        return res

    return result


# print(get_owned('1017889758313197658', True))

async def check_wallet_exist(address):
    users_collection = db['users']
    # Upsert user
    # print(address)

    result = await users_collection.find_one({
        "$or": [
            {"address": address},
            {"linked_addresses": {'$elemMatch': {"$eq": address}}
             },
        ]
    })
    discord_user_exist = result is not None #and result.get('discord_id')
    # print(f"Found user {result}")

    return discord_user_exist


async def get_user(address, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']
    # Upsert user
    # print(address)

    user_id = str(address)
    result = await users_collection.find_one({"address": user_id})
    # print(result)
    # print(f"Found user {result}")

    return result


async def get_move(name, stars=0):
    # print(name)

    result = await move_collection.find_one({"move_name": name})
    if stars > 0 and result and stars > result['stars']:
        new_move = await db['PurpleEffectList'].find_one(
            {'purple_id': result['purple_id'] + max(0, stars - result['stars'])},
            {'_id': 0, 'strings': 1}
        )
        result['notes'] = '\n > '.join(new_move.get('strings'))

    # print(f"Found move {result}")

    return result


async def get_zerpmon_by_nftID(nftID):
    zerpmon_collection = db['MoveSets']
    result = await zerpmon_collection.find_one({"nft_id": nftID})

    return result


async def get_zerpmon(name, mission=False, user_id=None, pvp=False):
    candy = None
    if mission:
        zerpmon_collection = db['MoveSets2']
    else:
        zerpmon_collection = db['MoveSets']
        if user_id:
            candy = (await get_active_candies(user_id)).get(name)
    # print(name)

    result = await zerpmon_collection.find_one({"name": name})
    if result is None:
        result = await zerpmon_collection.find_one({"nft_id": str(name).upper()})
    flair = result.get('z_flair', None)
    result['name2'] = result['name'] + (f' {flair}' if flair else '')
    if candy:
        if candy.get('type1', {}).get('expire_ts', 0) > time.time():
            await update_stats_candy(result, candy['type1']['type'])
        if not pvp and candy.get('type2', {}).get('expire_ts', 0) > time.time():
            await update_stats_candy(result, candy['type2']['type'])
    # print(f"Found Zerpmon {result}")

    return result


async def save_zerpmon_winrate(all_rounds: list):
    zerpmon_collection = db['MoveSets']
    # print(winner_name, loser_name)
    batch_operations = []
    for round_stat in all_rounds:
        total = round_stat['total'] + len(round_stat['rounds'])
        new_wr = ((round_stat['winrate'] * round_stat['total']) + (100 * round_stat['rounds'].count(1))) / total
        batch_operations.append(
            UpdateOne(
                {'name': round_stat['name']},
                {'$set':
                     {'total': total,
                      'winrate': new_wr,
                      }
                 }
            )
        )

    result = await zerpmon_collection.bulk_write(batch_operations)
    return result.acknowledged


async def temp_move_update(document):
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
        miss_percent = [i for i in document['moves'] if i['color'] == 'miss'][0]['percent']
        percent_change = 3.33 * (document['level'] // 10)
        if percent_change == 9.99:
            percent_change = 10
        percent_change = percent_change if percent_change < miss_percent else miss_percent
        count = len([i for i in document['moves'] if i['name'] != "" and i['color'] != "blue"]) - 1
        print(document)
        for i, move in enumerate(document['moves']):
            if move['color'] == 'miss':
                move['percent'] = round(move['percent'] - percent_change, 2)
                document['moves'][i] = move
            elif move['name'] != "" and move['percent'] > 0 and move['color'] != "blue":
                move['percent'] = round(move['percent'] + (percent_change / count), 2)
                document['moves'][i] = move


async def get_rand_zerpmon(level, lure_type=None, includeOmni=True):
    zerpmon_collection = db['MoveSets2']
    if lure_type is None:
        query = {}
    else:
        query = {'zerpmonType': {'$elemMatch': {'$eq': lure_type.lower()}}}
    if not includeOmni:
        query['isOmni'] = {'$exists': False}
    random_doc = await zerpmon_collection.aggregate([
        {'$match': query},
        {'$sample': {'size': 1}},
        {'$limit': 1}
    ]).to_list(None)
    zerp = random_doc[0]
    zerp['level'] = level
    await temp_move_update(zerp)
    zerp['name2'] = zerp['name']
    # print(random_doc[0])
    return zerp


async def get_all_t(substr=None):
    t_collection = db['trainers']
    if not substr:
        data = await t_collection.find({}).to_list(None)
    else:
        data = await t_collection.find(
            {'name': {'$regex': re.compile(f"^{substr}", re.IGNORECASE)}},
            {'_id': 0, 'name': 1, 'type': 1, 'affinity': 1}) \
            .to_list(25)
    return data


async def get_all_z(substr=None, test=False):
    zerpmon_collection = db['MoveSets'] if not test else db['MoveSets2']
    if not substr:
        data = await zerpmon_collection.find({}).to_list(None)
    else:
        data = await zerpmon_collection.find(
            {'name': {'$regex': re.compile(f"^{substr}", re.IGNORECASE)}},
            {'_id': 0, 'name': 1, 'zerpmonType': 1}) \
            .to_list(25)
    return data


async def update_image(name, url):
    zerpmon_collection = db['MoveSets']
    await zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'image': url}})


async def update_type(name, attrs):
    zerpmon_collection = db['MoveSets']
    await zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'attributes': attrs}})


async def update_level(name, new_lvl):
    zerpmon_collection = db['MoveSets']
    await zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'level': new_lvl}})


async def update_zerpmon_alive(zerpmon, serial, user_id):
    users_collection = db['users']
    # if 'buff_eq' in zerpmon:
    #     del zerpmon['buff_eq']
    # if 'eq_applied_miss' in zerpmon:
    #     del zerpmon['eq_applied_miss']
    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {'$set': {f'zerpmons.{serial}.active_t': zerpmon['active_t']}})
    # print(r)


async def update_battle_count(user_id, num):
    from utils.checks import get_next_ts
    users_collection = db['users']
    new_ts = await get_next_ts()
    r = await users_collection.find_one({'discord_id': str(user_id)})
    if 'battle' in r and r['battle']['num'] > 0 and new_ts - r['battle']['reset_t'] > 80000:
        num = -1
    await users_collection.update_one({'discord_id': str(user_id)},
                                      {'$set': {
                                          'battle.num': num + 1,
                                          'battle.reset_t': new_ts
                                        }
                                      })
    # print(r)

async def update_last_battle_t_gym(user_id, last_battle_t, final_ts=None):
    users_collection = db['users']
    if last_battle_t == 0:
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {
                                                  '$set': {'gym.last_battle_t': int(time.time()) if not final_ts else final_ts}
                                              })
    else:
        r = await users_collection.update_one({'discord_id': str(user_id), 'gym.last_battle_t': last_battle_t},
                                              {
                                                  '$set': {'gym.last_battle_t': int(time.time()) if not final_ts else final_ts}
                                              })
    return r.modified_count == 1

async def update_last_battle_t(user_id, last_battle_t,):
    print('update_last_battle_t', user_id, last_battle_t)
    users_collection = db['users']
    if last_battle_t == 0:
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {
                                                  '$set': {'battle.last_battle_t': int(time.time())}
                                              })
    else:
        r = await users_collection.update_one({'discord_id': str(user_id), 'battle.last_battle_t': last_battle_t},
                                              {
                                                  '$set': {'battle.last_battle_t': int(time.time())}
                                              })
    return r.modified_count == 1

async def update_user_wr(user_id, win, total_m, is_reset):
    from utils.checks import get_next_ts
    users_collection = db['users']
    new_ts = int(await get_next_ts())
    if is_reset:
        update_operation = {
            '$set': {
                'battle.reset_t': new_ts,
                'battle.num': 1,
                'total_matches': total_m + 1,
            },
            '$inc': {

                'win': 1 if win else 0,
                'loss': 0 if win else 1,
            }
        }
    else:
        update_operation = {
            '$set': {
                'battle.reset_t': new_ts,
                'total_matches': total_m + 1,
            },
            '$inc': {
                'battle.num': 1,
                'win': 1 if win else 0,
                'loss': 0 if win else 1,
            }
        }

    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          update_operation,
                                          upsert=True)
    return r.acknowledged


async def update_pvp_user_wr(user_id, win, recent_deck=None, b_type=None):
    users_collection = db['users']

    query = {'$inc': {'pvp_win': win, 'pvp_loss': abs(1 - win)}}
    if recent_deck is not None:
        deck, e_deck = recent_deck.get('z'), recent_deck.get('e')
        if b_type != 5:
            z1_deck, eq1_deck = {}, {}
            for i in range(b_type):
                z1_deck[str(i)] = deck[str(i)]
                eq1_deck[str(i)] = e_deck[str(i)]
            if 'trainer' in deck:
                z1_deck['trainer'] = deck['trainer']
        else:
            z1_deck, eq1_deck = deck, e_deck
        recent_key = 'recent_deck' + (f'{b_type}' if b_type != 3 else '')
        query['$set'] = {recent_key: z1_deck, recent_key + '_eq': eq1_deck}
    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          query,
                                          upsert=True)

    return r.acknowledged


async def save_mission_mode(user_id, mode):
    users_collection = db['users']
    user_id = str(user_id)
    r = await users_collection.update_one({'discord_id': user_id}, {'$set': {'xp_mode': mode}})
    return r.acknowledged


async def get_top_players(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'win': {'$exists': True}}
    top_users = await users_collection.find(query).sort('win', DESCENDING).limit(10).to_list(None)
    top_users = [i for i in top_users]

    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = await users_collection.find_one({'discord_id': user_id})
        if curr_user and 'win' not in curr_user:
            curr_user['win'] = 0
            curr_user['loss'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = await users_collection.count_documents({'win': {'$gt': curr_user['win']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return top_users


async def get_pvp_top_players(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'pvp_win': {'$exists': True}}
    top_users = await users_collection.find(query).sort('pvp_win', DESCENDING).limit(10).to_list(None)
    top_users = [i for i in top_users]
    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = await users_collection.find_one({'discord_id': user_id})
        if curr_user and 'pvp_win' not in curr_user:
            curr_user['pvp_win'] = 0
            curr_user['pvp_loss'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = await users_collection.count_documents({'pvp_win': {'$gt': curr_user['pvp_win']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return [i for i in top_users]


async def get_top_purchasers(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'xrp_spent': {'$exists': True}}
    top_users = await users_collection.find(query).sort('xrp_spent', DESCENDING).limit(10).to_list(None)
    top_users = [i for i in top_users]
    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = await users_collection.find_one({'discord_id': user_id})
        if curr_user and 'xrp_spent' not in curr_user:
            curr_user['xrp_spent'] = 0
            curr_user['mission_purchase'] = 0
            curr_user['revive_purchase'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = await users_collection.count_documents({'xrp_spent': {'$gt': curr_user['xrp_spent']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return [i for i in top_users]


async def get_ranked_players(user_id, field='rank'):
    users_collection = db['users']
    user_id = str(user_id)
    query = {field: {'$exists': True}}
    top_users = await users_collection.find(query).sort(f'{field}.points', DESCENDING).to_list(None)
    curr_user = await users_collection.find_one({'discord_id': user_id})
    if curr_user:
        curr_user_rank = await users_collection.count_documents(
            {f'{field}.points': {'$gt': curr_user[field]['points'] if field
                                                                      in curr_user else 0}})
        curr_user['ranked'] = curr_user_rank + 1
        top_users_count = await users_collection.count_documents(query)

        rank_limit = 4  # Number of players above and below to show
        rank_above = max(0, curr_user['ranked'] - rank_limit)
        rank_below = min(top_users_count, curr_user['ranked'] + rank_limit + 1)

        top_users = list(top_users[rank_above:rank_below])
        for i, user in enumerate(top_users):
            top_users[i]['ranked'] = rank_above + 1
            rank_above += 1

        if curr_user['discord_id'] not in [i['discord_id'] for i in top_users]:
            if field not in curr_user:
                curr_user[field] = {'tier': 'Unranked', 'points': 0}
            top_users.append(curr_user)
        return top_users
    else:
        users = list(top_users[:7])
        for i, user in enumerate(users):
            users[i]['ranked'] = i + 1
        return users


async def get_same_ranked_p(user_id, rank_tier, field='rank'):
    users_collection = db['users']
    if rank_tier == 'Unranked':
        query = {
            '$or': [
                {f'{field}.tier': rank_tier},  # Check if the field is equal to 'Unranked'
                {field: {'$exists': False}}  # Check if the field doesn't exist
            ]
        }
    else:
        rank_list = list(config.RANKS.keys())
        c_idx = rank_list.index(rank_tier)
        l_tier, h_tier = c_idx - 1, c_idx + 1
        print(c_idx)
        query = {
            '$or': [
                {f'{field}.tier': rank_tier},
                {f'{field}.tier': rank_list[l_tier]},
                {f'{field}.tier': rank_list[h_tier]},
            ]
        }
    top_users = await users_collection.find(query).sort(f'{field}.points', DESCENDING).to_list(None)
    return [i for i in top_users if i['discord_id'] != user_id]


async def add_revive_potion(address, inc_by, purchased=False, amount=0, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']
    query = {'revive_potion': inc_by}
    if purchased:
        query['xrp_spent'] = amount
        query['revive_purchase'] = inc_by
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['revive_potion'] = {'$gte': abs(inc_by)}
    res = await users_collection.update_one(filter_,
                                            {'$inc': query},
                                            upsert=True)

    return res.modified_count == 1


async def add_mission_potion(address, inc_by, purchased=False, amount=0, db_sep=None):
    users_collection = db['users'] if db_sep is None else db_sep['users']

    query = {'mission_potion': inc_by}
    if purchased:
        query['xrp_spent'] = amount
        query['mission_purchase'] = inc_by
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['mission_potion'] = {'$gte': abs(inc_by)}
    print(filter_, query)
    res = await users_collection.update_one(filter_,
                                            {'$inc': query},
                                            upsert=True)
    # print(r)
    return res.modified_count == 1


async def add_gym_refill_potion(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']

    query = {'gym.refill_potion': inc_by}
    filter_ = {'address': address}
    if purchased:
        query['zrp_spent'] = amount
        query['gym.refill_purchase'] = inc_by
    if inc_by < 0:
        filter_['gym.refill_potion'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one({'address': str(address)},
                                      {'$inc': query},
                                      upsert=True)
    # print(r)
    return r.modified_count == 1


async def reset_respawn_time(user_id):
    users_collection = db['users']
    old = await users_collection.find_one({'discord_id': str(user_id)})

    for k, z in old['zerpmons'].items():
        old['zerpmons'][k]['active_t'] = 0

    old['battle.num'] = 0
    old['battle.reset_t'] = -1

    r = await users_collection.find_one_and_update({'discord_id': str(user_id)},
                                                   {'$set': old},
                                                   return_document=ReturnDocument.AFTER)


async def reset_all_gyms():
    users_collection = db['users']
    old = await users_collection.find().to_list(None)
    for user in old:
        gym_obj = user.get('gym', {})
        gym_obj['won'] = {}
        gym_obj['active_t'] = 0
        gym_obj['gp'] = 0
        query = {'$set': {'gym': gym_obj}}
        r = await users_collection.find_one_and_update({'discord_id': user['discord_id']},
                                                       query,
                                                       return_document=ReturnDocument.AFTER)


async def update_trainer_deck(trainer_serial, user_id, deck_no, gym=False):
    users_collection = db['users']
    if gym:
        update_query = {
            f'gym_deck.{deck_no}.trainer': trainer_serial
        }
    else:
        update_query = {
            f'battle_deck.{deck_no}.trainer': trainer_serial
        }

    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {'$set': update_query})

    if r.acknowledged:
        return True
    else:
        return False


async def update_mission_trainer(trainer_serial, user_id):
    users_collection = db['users']
    update_query = {
        f'mission_trainer': trainer_serial
    }

    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {'$set': update_query})

    if r.acknowledged:
        return True
    else:
        return False


async def update_mission_deck(new_deck, user_id):
    users_collection = db['users']

    # doc = await users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    # arr = {} if "mission_deck" not in doc or doc["mission_deck"] == {} else doc["mission_deck"]
    # if arr != {}:
    #     for k, v in arr.copy().items():
    #         if v == zerpmon_id:
    #             del arr[k]
    #
    # arr[str(place - 1)] = zerpmon_id
    arr = new_deck
    # save the updated document
    r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'mission_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


async def clear_mission_deck(user_id):
    users_collection = db['users']
    n_deck = {str(i): None for i in range(20)}
    r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'mission_deck': n_deck}})

    if r.acknowledged:
        return True
    else:
        return False


async def update_battle_deck(deck_no, deck_name, new_deck, eqs, user_id):
    users_collection = db['users']

    doc = await users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else \
        doc["battle_deck"]

    arr[deck_no] = new_deck
    q = {f'equipment_decks.battle_deck.{deck_no}': eqs,
         'battle_deck': arr}
    if deck_name:
        q[f'deck_names.battle_decks.{deck_no}'] = deck_name
    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {"$set": q})

    if r.acknowledged:
        return True
    else:
        return False


async def clear_battle_deck(deck_no, user_id, gym=False):
    users_collection = db['users']
    if gym:
        r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'gym_deck.{deck_no}': {}}})
    else:
        r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'battle_deck.{deck_no}': {}}})

    if r.acknowledged:
        return True
    else:
        return False


async def update_gym_deck(deck_no, deck_name, new_deck, eqs, user_id):
    users_collection = db['users']

    doc = await users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "gym_deck" not in doc or doc["gym_deck"] == {} else doc[
        "gym_deck"]

    arr[deck_no] = new_deck
    q = {f'equipment_decks.gym_deck.{deck_no}': eqs,
         'gym_deck': arr,

         }
    if deck_name:
        q[f'deck_names.gym_decks.{deck_no}'] = deck_name
    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {"$set": q})

    if r.acknowledged:
        return True
    else:
        return False


async def clear_gym_deck(deck_no, user_id):
    users_collection = db['users']
    r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'gym_deck.{deck_no}': {}}})
    if r.acknowledged:
        return True
    else:
        return False


async def swap_names(deck_names, deck_no):
    if deck_names.get(deck_no) and deck_names.get('0'):
        deck_names['0'], deck_names[deck_no] = deck_names[deck_no], deck_names['0']
    elif deck_names.get('0'):
        deck_names[deck_no] = deck_names['0']
        del deck_names['0']
    elif deck_names.get(deck_no):
        deck_names['0'] = deck_names[deck_no]
        del deck_names[deck_no]


async def set_default_deck(deck_no, doc, user_id, type_: str):
    users_collection = db['users']
    if type_ == config.GYM_DECK:
        arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "gym_deck" not in doc or doc["gym_deck"] == {} else doc[
            "gym_deck"]
        # Deck names exchange
        deck_name_key = type_ + 's'
        deck_names = doc.get('deck_names', {}).get(deck_name_key, {})
        await swap_names(deck_names, deck_no)
        #
        arr[deck_no], arr['0'] = arr['0'], arr.get(deck_no, {})
        eq_deck = doc['equipment_decks']['gym_deck']
        eq_deck[deck_no], eq_deck['0'] = eq_deck['0'], eq_deck.get(deck_no, {})

        # save the updated document
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {"$set": {'gym_deck': arr, 'equipment_decks.gym_deck': eq_deck,
                                                        f'deck_names.{deck_name_key}': deck_names}})
    elif type_ == config.BATTLE_DECK:
        arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else \
            doc["battle_deck"]
        # Deck names exchange
        deck_name_key = type_ + 's'
        deck_names = doc.get('deck_names', {}).get(deck_name_key, {})
        await swap_names(deck_names, deck_no)
        #
        arr[deck_no], arr['0'] = arr['0'], arr.get(deck_no, {})
        eq_deck = doc['equipment_decks']['battle_deck']
        eq_deck[deck_no], eq_deck['0'] = eq_deck['0'], eq_deck.get(deck_no, {})
        # save the updated document
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {"$set": {'battle_deck': arr, 'equipment_decks.battle_deck': eq_deck,
                                                        f'deck_names.{deck_name_key}': deck_names}})
    elif type_ == 'br_champion_decks':
        arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "br_champion_decks" not in doc or doc[
            "br_champion_decks"] == {} else \
            doc["br_champion_decks"]
        # Deck names exchange
        #
        arr[deck_no], arr['0'] = arr['0'], arr.get(deck_no, {})
        # save the updated document
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {"$set": {'br_champion_decks': arr}
                                               })
    else:
        users_collection = db['temp_user_data']
        arr = doc["battle_deck"]
        arr[deck_no], arr['0'] = arr['0'], arr.get(deck_no, {})
        eq_deck = doc['equipment_decks']
        eq_deck[deck_no], eq_deck['0'] = eq_deck['0'], eq_deck.get(deck_no, {})
        # save the updated document
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {"$set": {'battle_deck': arr, 'equipment_decks': eq_deck}})

    if r.acknowledged:
        return True
    else:
        return False


async def reset_deck():
    users_collection = db['users']

    doc = await users_collection.find().to_list(None)

    for user in doc:
        r = await users_collection.update_one({'discord_id': str(user['discord_id'])}, {"$set": {'battle_deck': {}}})


async def get_deck_names(d_id: str):
    users_collection = db['users']
    doc = await users_collection.find_one({'discord_id': d_id}, {'_id': 0, 'deck_names': 1, 'br_champion_decks': 1})
    return doc


async def revive_zerpmon(user_id, old):
    users_collection = db['users']
    addr = old['address']

    for k, z in old['zerpmons'].items():
        old['zerpmons'][k]['active_t'] = 0
    success = await add_revive_potion(addr, -1)
    if success:
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {'$set': {'zerpmons': old['zerpmons']}}, )
        return r.acknowledged
    return False


async def mission_refill(user_id, addr):
    users_collection = db['users']
    # old = await users_collection.find_one({'discord_id': str(user_id)})
    # addr = old['address']
    q = {
        'battle.num': 0,
         'battle.reset_t': -1
        }

    success = await add_mission_potion(addr, -1)
    if success:
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {'$set': q}, )
        return r.acknowledged
    return False


async def gym_refill(user_id):
    users_collection = db['users']
    old = await users_collection.find_one({'discord_id': str(user_id)})
    addr = old['address']
    if 'gym' in old:
        for i in old['gym']['won']:
            if old['gym']['won'][i]['lose_streak'] > 0:
                old['gym']['won'][i]['next_battle_t'] = -1
                # old['gym']['won'][i]['lose_streak'] -= 1
        r = await users_collection.update_one({'discord_id': str(user_id)},
                                              {'$set': {'gym': old['gym']}}, )
        await add_gym_refill_potion(addr, -1)

        if r.acknowledged:
            return True
        else:
            return False
    return False


async def add_xrp(user_id, amount):
    users_collection = db['users']

    r = await users_collection.find_one_and_update({'discord_id': str(user_id)},
                                                   {'$inc': {'xrp_earned': amount}},
                                                   upsert=True,
                                                   return_document=ReturnDocument.AFTER)
    # print(r)


async def add_candy_fragment(addr, qty=1):
    users_collection = db['users']
    await users_collection.update_one({'address': addr}, {'$inc': {'candy_frag': qty}})


async def combine_candy_frag(addr, combine_to_key):
    users_collection = db['users']
    res = await users_collection.update_one({'address': addr, 'candy_frag': {'$gte': 7}},
                                            {'$inc': {'candy_frag': -7, combine_to_key: 1}})
    return res.acknowledged


async def add_candy_slot(zerp_name):
    zerpmon_collection = db['MoveSets']
    res = await zerpmon_collection.update_one({'name': zerp_name}, {'$inc': {'extra_candy_slot': 1}})
    return res.acknowledged


async def add_xp(zerpmon_name, user_address, xp_add, ascended=False, zerp_obj=None):
    zerpmon_collection = db['MoveSets']

    old = await zerpmon_collection.find_one({'name': zerpmon_name}) if zerp_obj is None else zerp_obj
    xp_mul = 1
    if old.get('evolvedFrom'):
        stage = [i['value'] for i in old['attributes'] if i['trait_type'] == 'Evolution Stage']
        if len(stage) > 1:
            if stage[0] == 'Evo 1':
                xp_mul = 1.5
            elif stage[0] == 'Evo 2':
                xp_mul = 2

    lvl_up, rewards = False, {}
    if old:
        level = old.get('level', 0)
        if level == 0:
            level = 1
        xp = old.get('xp', 0)
        cur_lvl = await level_collection.find_one({'level': level}) if (level < 30 or ascended) else None
        next_lvl = await level_collection.find_one({'level': level + 1}) if (level < 30 or ascended) else None

        if next_lvl and xp + xp_add >= next_lvl['xp_required'] * xp_mul:
            left_xp = (xp + xp_add) - next_lvl['xp_required'] * xp_mul
            if (next_lvl['level'] == 30 and not ascended) or (next_lvl['level'] == 60 and ascended):
                left_xp = 0
            query = {'$set': {'level': next_lvl['level'], 'xp': left_xp}}
            if zerp_obj:
                query['$inc'] = {'licorice': 1}
            doc = await zerpmon_collection.find_one_and_update({'name': zerpmon_name}, query,
                                                               return_document=ReturnDocument.AFTER)
            xp = doc.get('xp')
            r_potion = next_lvl['revive_potion_reward']
            m_potion = next_lvl['mission_potion_reward']
            gym_r_potion = next_lvl.get('gym_refill_reward', 0)
            candy_slot = next_lvl.get('candy_slot', 0)
            candy_frags = next_lvl.get('candy_frags', 0)
            candy_reward = next_lvl.get('extra_candy', None)
            candy_reward_cnt = next_lvl.get('extra_candy_cnt', 0)
            lvl_up = True
            if r_potion + m_potion + gym_r_potion + candy_slot == 0:
                await add_candy_fragment(user_address)
                rewards['cf'] = 1
            else:
                if r_potion + m_potion > 0:
                    await add_revive_potion(user_address, r_potion)
                    await add_mission_potion(user_address, m_potion)
                    rewards['rp'] = r_potion
                    rewards['mp'] = m_potion
                if gym_r_potion:
                    await add_gym_refill_potion(user_address, gym_r_potion)
                    await globals().get(f'add_{candy_reward}')(user_address, candy_reward_cnt)
                    rewards['grp'] = gym_r_potion
                    rewards['extra_candy'] = candy_reward
                    rewards['extra_candy_cnt'] = candy_reward_cnt
                elif candy_slot > 0:
                    await add_candy_fragment(user_address, candy_frags)
                    await add_candy_slot(zerpmon_name)
                    rewards['cs'] = 1
                    rewards['cf'] = candy_frags
            if (level + 1) >= 10 and (level + 1) % 10 == 0:
                await update_moves(doc)

        else:
            maxed = old.get('maxed_out', 0)
            if level < 30 or (ascended and level < 60):
                doc = await zerpmon_collection.find_one_and_update({'name': zerpmon_name}, {'$inc': {'xp': xp_add}},
                                                                   return_document=ReturnDocument.AFTER)
                xp = doc.get('xp')
            elif (level == 30 or level == 60) and maxed == 0:
                await zerpmon_collection.update_one({'name': zerpmon_name}, {'$set': {'maxed_out': 1}})
    else:
        # Zerpmon not found, handle the case accordingly
        # For example, you can raise an exception or return False
        return False, False, False

    # Rest of the code for successful operation
    return True, lvl_up, rewards, xp


class AddXPTrainerResult:
    def __init__(self, is_level_up: bool, rewards: dict | None, new_level: int, xp_left: int, new_xp: int):
        self.is_level_up = is_level_up
        self.rewards = rewards
        self.new_level = new_level
        self.xp_left = xp_left
        self.new_xp = new_xp


async def add_xp_trainer(nft_id: str, address: str, xp: int):
    trainer_col = db['trainers']
    level_col = db['levels_trainer_trn'] if nft_id.startswith('trn-') else db['levels_trainer']

    trainer = await trainer_col.find_one({'nft_id': nft_id, 'isCollab': {'$exists': False}})
    max_level = 30

    if not trainer or trainer.get('level') == max_level:
        return None

    cur_level = trainer.get('trainer_level', 0)

    levels = await level_col.find({}, projection={'_id': 0}).sort('level', 1).to_list(None)
    max_level_obj = levels[max_level - 1]
    cur_level_obj = levels[cur_level - 1] if cur_level > 0 else None
    final_xp = (cur_level_obj['total_xp'] if cur_level_obj else 0) + trainer.get('trainer_xp', 0) + xp

    print(max_level_obj['total_xp'], cur_level_obj, final_xp, trainer.get('trainer_xp', 0), xp)
    new_xp = 0
    if final_xp > max_level_obj['total_xp']:
        next_level_obj = max_level_obj
    else:
        next_level_obj = next((val for idx, val in enumerate(levels) if
                               val['total_xp'] <= final_xp < levels[idx + 1]['total_xp']), None)
        if next_level_obj:
            new_xp = final_xp - next_level_obj['total_xp']
        else:
            new_xp = final_xp

    # if not next_level_obj:
    #     raise Exception(f'No new level (args: {nft_id} {address} {xp})')

    is_level_up = next_level_obj['level'] > cur_level if next_level_obj else False
    if is_level_up:
        trainer['level'] = next_level_obj['level']
        rewards = {}
        r_potion = 0
        m_potion = 0
        candy_frags = 0
        lvl_up = True
        for idx in range(cur_level, next_level_obj['level']):
            next_lvl = levels[idx]
            r_potion += next_lvl['revive_potion_reward']
            m_potion += next_lvl['mission_potion_reward']
            candy_frags += next_lvl.get('candy_frags', 0)
        if candy_frags > 0:
            await add_candy_fragment(address, candy_frags)
            rewards['cf'] = candy_frags
        if r_potion > 0:
            await add_revive_potion(address, r_potion)
            rewards['rp'] = r_potion
        if m_potion > 0:
            await add_mission_potion(address, m_potion)
            rewards['mp'] = m_potion
        await trainer_col.update_one(
            {'nft_id': nft_id},
            {
                '$set': {
                    'trainer_xp': new_xp,
                    'trainer_level': next_level_obj['level'],
                },
            },
        )
        return AddXPTrainerResult(
            is_level_up=is_level_up,
            rewards=rewards,
            new_level=next_level_obj['level'],
            xp_left=levels[min(next_level_obj['level'], 30 - 1)]['xp_required'] - new_xp,
            new_xp=new_xp
        )
    else:
        await trainer_col.update_one({'nft_id': nft_id}, {'$set': {'trainer_xp': new_xp}})
        return AddXPTrainerResult(
            is_level_up=is_level_up,
            rewards=None,
            new_level=cur_level,
            xp_left=levels[min(next_level_obj['level'] if next_level_obj else 0, 30 - 1)]['xp_required'] - new_xp,
            new_xp=new_xp
        )


async def get_lvl_xp(zerpmon_name, in_mission=False, get_candies=False, double_xp=False, ret_doc=False) -> tuple:
    zerpmon_collection = db['MoveSets']

    old = await zerpmon_collection.find_one({'name': zerpmon_name})
    level = old['level'] if 'level' in old else 0
    xp_mul = 1
    if old.get('evolvedFrom'):
        stage = [i['value'] for i in old['attributes'] if i['trait_type'] == 'Evolution Stage']
        if len(stage) > 1:
            if stage[0] == 'Evo 1':
                xp_mul = 1.5
            elif stage[0] == 'Evo 2':
                xp_mul = 2
    # maxed = old.get('maxed_out', 0)
    # if maxed == 0 and in_mission and (level - 1) >= 10 and (level - 1) % 10 == 0 and (
    #         old['xp'] == 0 or (old['xp'] == 10 and double_xp)):
    #     update_moves(old)
    if level > 60:
        level = 60
    # last_lvl = await level_collection.find_one({'level': (level - 1) if level > 1 else 1})
    next_lvl = await level_collection.find_one({'level': min(60, level + 1)})
    if 'level' in old and 'xp' in old:

        vals = old['level'], old['xp'], next_lvl['xp_required'] * xp_mul if not get_candies else (
            next_lvl['xp_required'] * xp_mul, old.get('white_candy', 0)), \
               next_lvl['revive_potion_reward'] if not get_candies else old.get('gold_candy', 0), \
               next_lvl['mission_potion_reward'] if not get_candies else old.get('licorice', 0)
    else:
        vals = 0, 0, next_lvl['xp_required'] * xp_mul if not get_candies else (
            next_lvl['xp_required'] * xp_mul, old.get('white_candy', 0)), \
               next_lvl['revive_potion_reward'] if not get_candies else old.get('gold_candy', 0), \
               next_lvl['mission_potion_reward'] if not get_candies else old.get('licorice', 0)
    if ret_doc:
        vals = vals, old
    return vals


# RANK QUERY

async def update_rank(user_id, win, decay=False, field='rank'):
    users_collection = db['users']
    usr = await get_owned(user_id)
    next_rank = None
    if field in usr:
        rank = usr[field]
    else:
        rank = {
            'tier': 'Unranked',
            'points': 0,
        }
    user_rank_d = config.RANKS[rank['tier']].copy()
    if decay:
        decay_tiers = config.TIERS[-2:]
        rank['points'] -= 50 if rank['tier'] == decay_tiers[0] else 100
    elif win is None:
        pass
    elif win:
        rank['points'] += user_rank_d['win']
    else:
        rank['points'] -= user_rank_d['loss']
        if rank['points'] < 0:
            return 0, rank, next_rank
    if rank['points'] >= user_rank_d['h']:
        next_rank = [r for r, v in config.RANKS.items() if v['l'] == user_rank_d['h']][0]
        rank['tier'] = next_rank
    elif rank['points'] < user_rank_d['l']:
        next_rank = [r for r, v in config.RANKS.items() if v['h'] == user_rank_d['l']][0]
        rank['tier'] = next_rank
    if not decay:
        rank['last_battle_t'] = time.time()
    if rank['points'] > 8000:
        user_rank_d['win'] -= rank['points'] % 8000
        rank['points'] = 8000
    await users_collection.update_one({'discord_id': str(user_id)},
                                      {'$set': {field: rank}}
                                      )
    return 0 if win is None else (user_rank_d['win'] if win else user_rank_d['loss']), rank, next_rank
    # print(r)


async def get_random_doc_with_type(type_value=None, limit=5, level=None, includeOmni=True):
    collection = db['MoveSets2']
    if type_value is None:
        query = {}
    else:
        query = {'zerpmonType': {'$elemMatch': {'$eq': type_value.lower()}}}
    if not includeOmni:
        query['isOmni'] = {'$exists': False}
    random_documents = await collection.aggregate([
        {'$match': query},
        {'$sample': {'size': limit}}
    ]).to_list(None)

    if random_documents:
        random_documents = list(random_documents)
        for doc in random_documents:
            del doc['_id']
            if level is not None and level >= 10:
                doc['level'] = level
                await update_moves(doc, False, effective=True)
            doc['name2'] = doc['name']
        print(random_documents)
        return random_documents
    else:
        return None


async def choose_gym_zerp():
    collection_name = 'gym_zerp'
    gym_col = db[collection_name]
    for leader_type in config.GYMS:
        leader_name = f'{leader_type} Gym Leader'
        gym_obj = {'name': leader_name,
                   'zerpmons': None,
                   'image': f'./static/gym/{leader_name}.png',
                   'bg': f'./static/gym/{leader_type}.png'}
        while gym_obj['zerpmons'] is None:
            gym_obj['zerpmons'] = await get_random_doc_with_type(leader_type, includeOmni=False)
        await gym_col.update_one({'name': leader_name},
                                 {'$set': gym_obj}, upsert=True)


# asyncio.run(choose_gym_zerp())

async def get_gym_leader(gym_type):
    collection_name = 'gym_zerp'
    gym_col = db[collection_name]
    leader_name = f'{gym_type} Gym Leader'
    res = await gym_col.find_one({'name': leader_name})
    return res


async def reset_gym(address, gym_obj, gym_type, lost=True, skipped=False, reset=False):
    users_collection = db['users']
    if gym_obj == {}:
        gym_obj = {
            'won': {
                gym_type: {
                    'stage': 1,
                    'next_battle_t': (await get_next_ts(1)) if lost else 0,
                    'lose_streak': 1
                }
            },
            'active_t': 0,
            'gp': 0
        }
        await users_collection.update_one(
            {'address': address},
            {'$set': {'gym': gym_obj}}
        )
    else:
        if 'won' not in gym_obj:
            gym_obj['won'] = {}
        l_streak = 1 if gym_type not in gym_obj['won'] else (gym_obj['won'][gym_type]['lose_streak'] + 1)
        reset_limit = 4
        if skipped:
            reset_limit = 3
        is_reset = l_streak >= reset_limit and reset
        gym_obj['won'][gym_type] = {
            'stage': 1 if is_reset else (
                gym_obj['won'][gym_type]['stage'] if gym_type in gym_obj['won'] else 1),
            'next_battle_t': (await get_next_ts(1)) if lost else (
                gym_obj['won'][gym_type]['next_battle_t'] if gym_type in gym_obj['won'] else 0),
            'lose_streak': 0 if reset else (l_streak if skipped or lost else l_streak - 1)
        }
        await users_collection.update_one(
            {'address': address},
            {'$set': {'gym.won': gym_obj['won']}}
        )


async def add_gp_queue(user_data, gp, block_number=1):
    address = user_data['address']
    match_cnt = user_data['gym'].get('match_cnt', 0) if 'gym' in user_data else 1
    uid = f'gym-{address}-{match_cnt}'
    amt = round(gp / (2 ** block_number), 2)
    queue_query = {
        'uniqueId': uid,
        'type': 'Payment',
        'destination': address,
        'from': 'gym',
        'status': 'pending',
        'amount': amt,
        'currency': 'ZRP',
        'gp': gp,
        'destinationTag': user_data.get('destination_tag')
    }
    await db['general-txn-queue'].update_one(
        {'uniqueId': uid},
        {'$setOnInsert': queue_query},
        upsert=True
    )
    return amt


async def add_loan_txn_to_queue(address, paymentType, paymentAmount, memo=None, ts=None, db_sep=None, nft_sr=None):
    uid = f'{address}-{nft_sr}-{memo}-{int(ts)}'
    amt = round(paymentAmount, 3)
    queue_query = {
        'uniqueId': uid,
        'type': 'Payment',
        'destination': address,
        'from': 'loan',
        'status': 'pending',
        'amount': amt,
        'currency': paymentType,
        'ts': int(time.time()),
        'destinationTag': await get_destination_tag(address, db_sep=db_sep)
    }
    if memo:
        queue_query['memo'] = memo
    await (db if db_sep is None else db_sep)['general-txn-queue'].update_one({'uniqueId': uid},
                                             {'$setOnInsert': queue_query},
                                             upsert=True,
                                             )
    return amt


async def add_loan_nft_txn_to_queue(address, nft_id, memo=None):
    uid = f'{str(uuid.uuid4())}'
    queue_query = {
        'uniqueId': uid,
        'type': 'NFTokenCreateOffer',
        'destination': address,
        'from': 'loan',
        'status': 'pending',
        'nftokenID': nft_id,
        'amount': 0,
        'ts': int(time.time())
    }
    if memo:
        queue_query['memo'] = memo
    await db['general-txn-queue'].insert_one(
        queue_query
    )


async def add_wager_txn_to_gen_queue(user_data, currency, paymentAmount, memo=None, isAddress=False, ):
    address = user_data['address'] if not isAddress else user_data
    amt = round(paymentAmount, 3)
    queue_query = {
        'uniqueId': f'{str(uuid.uuid4())}',
        'type': 'Payment',
        'destination': address,
        'from': 'wager',
        'status': 'pending',
        'amount': amt,
        'currency': currency,
        'ts': int(time.time()),
        'destinationTag': user_data.get('destination_tag') if not isAddress else await get_destination_tag(user_data)
    }
    if memo:
        queue_query['memo'] = memo
    await db['general-txn-queue'].insert_one(queue_query, )
    return amt


async def add_tower_txn_to_gen_queue(user_data, uid, paymentAmount, memo=None):
    address = user_data['address']
    queue_query = {
        'uniqueId': f'{str(uuid.uuid4())}',
        'type': 'Payment',
        'destination': address,
        'from': 'tower',
        'status': 'pending',
        'amount': paymentAmount,
        'currency': 'ZRP',
        'ts': int(time.time()),
        'destinationTag': user_data.get('destination_tag')
    }
    if memo:
        queue_query['memo'] = memo
    await db['general-txn-queue'].update_one({'uniqueId': uid},
                                             {'$setOnInsert': queue_query},
                                             upsert=True)
    return True


async def update_gym_won(discord_id,
                         gym_obj,
                         gym_type,
                         stage,
                         resetTs,
                         last_battle_ts,
                         lost=False,
                         ):
    users_collection = db['users']
    next_day_ts = await get_next_ts(1)
    if lost:
        n_stage = stage
        reset_t = next_day_ts
    else:
        n_stage = stage + 1
        reset_t = config.gym_main_reset if config.gym_main_reset >= next_day_ts else resetTs
    if gym_obj == {}:
        gym_obj = {
            'won': {
                gym_type: {
                    'stage': n_stage,
                    'next_battle_t': reset_t,
                    'lose_streak': 1 if lost else 0
                }
            },
            'active_t': 0,
            'match_cnt': 1,
            'last_battle_t': last_battle_ts,
        }
        await users_collection.update_one(
            {'discord_id': str(discord_id)},
            {'$set': {'gym': gym_obj}}
        )
    else:
        if 'won' not in gym_obj:
            gym_obj['won'] = {}
        if stage + 1 >= 11:
            await log_user_gym(discord_id, gym_type, stage)
        gym_obj['won'][gym_type] = {
            'stage': n_stage if n_stage <= 20 else 1,
            'next_battle_t': reset_t,
            'lose_streak': gym_obj['won'].get(gym_type, {}).get('lose_streak', 0) + 1 if lost else 0
        }
        # gym_obj['gp'] += stage
        await users_collection.update_one(
            {'discord_id': str(discord_id)},
            {'$set': {f'gym.won.{gym_type}': gym_obj['won'][gym_type],
                      'gym.match_cnt': gym_obj.get('match_cnt', 0) + 1,
                      'gym.last_battle_t': last_battle_ts,
                      },
             }
        )


async def get_gym_leaderboard(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'gym': {'$exists': True}}
    top_users = await users_collection.find(query).sort('gym.gp', DESCENDING).to_list(None)
    curr_user = await users_collection.find_one({'discord_id': user_id})
    top_users_count = await users_collection.count_documents(query)
    if curr_user:
        curr_user_rank = await users_collection.count_documents(
            {'gym.gp': {'$gt': curr_user['gym']['gp'] if 'gym' in curr_user else 0}})
        curr_user['ranked'] = curr_user_rank + 1

        rank_limit = 4  # Number of players above and below to show
        rank_above = max(0, curr_user['ranked'] - rank_limit)
        rank_below = min(top_users_count, curr_user['ranked'] + rank_limit + 1)

        top_users = list(top_users[rank_above:rank_below])
        for i, user in enumerate(top_users):
            top_users[i]['ranked'] = rank_above + 1
            rank_above += 1

        if curr_user['discord_id'] not in [i['discord_id'] for i in top_users]:
            if 'gym' not in curr_user:
                curr_user['gym'] = {'won': {}, 'gp': 0, 'active_t': 0}
            top_users.append(curr_user)

    else:
        top_users = list(top_users[:7])
        for i, user in enumerate(top_users):
            top_users[i]['ranked'] = i + 1
            top_users[i]['rank_title'] = 'Trainer'
            # Set rank titles based on position

    for user in top_users:
        rank_position = user['ranked']
        if rank_position <= (top_users_count * 0.05):  # Top 5%
            user['rank_title'] = 'Legendary Trainer'
        elif rank_position <= (top_users_count * 0.13):  # Top 8%
            user['rank_title'] = 'Grand Warlord'
        elif rank_position <= (top_users_count * 0.23):  # Top 10%
            user['rank_title'] = 'Master Tamer'
        elif rank_position <= (top_users_count * 0.41):  # Top 10%
            user['rank_title'] = 'Elite Explorer'
        elif rank_position <= (top_users_count * 0.67):  # Top 10%
            user['rank_title'] = 'Apprentice Battler'
        else:
            user['rank_title'] = 'Novice Trainer'
    return top_users


async def update_user_bg(user_id, gym_type):
    users_collection = db['users']
    user_id = str(user_id)
    bg_value = f'{gym_type}'
    await users_collection.update_one({'discord_id': user_id},
                                      {'$push': {'bg': bg_value}})


async def update_user_flair(user_id, flair_name):
    users_collection = db['users']
    user_id = str(user_id)
    await users_collection.update_one({'discord_id': user_id},
                                      {'$push': {'flair': flair_name}})


async def add_bg(user_id, gym_type, type_):
    if type_ < 0:
        users_collection = db['users']
        user_id = str(user_id)
        bg_value = f'{gym_type}'
        user_obj = await users_collection.find_one({'discord_id': user_id}, {'bg': 1})
        user_obj['bg'].remove(bg_value)

        await users_collection.update_one(
            {'discord_id': user_id},
            {'$set': {'bg': user_obj['bg']}}
        )
    else:
        await update_user_bg(user_id, gym_type)


async def add_flair(user_id, flair_name, type_):
    if type_ < 0:
        users_collection = db['users']
        user_id = str(user_id)
        user_obj = await users_collection.find_one({'discord_id': user_id}, {'flair': 1})
        user_obj['flair'].remove(flair_name)
        await users_collection.update_one(
            {'discord_id': user_id},
            {'$set': {'flair': user_obj['flair']}}
        )
    else:
        await update_user_flair(user_id, flair_name)


async def set_user_bg(user_obj, gym_type):
    user_id = user_obj['discord_id']
    bgs = user_obj['bg']
    users_collection = db['users']
    bg_value = f'{gym_type}'
    index = bgs.index(bg_value)
    bgs[0], bgs[index] = bgs[index], bgs[0]
    await users_collection.update_one({'discord_id': user_id},
                                      {'$set': {'bg': bgs}})


async def set_user_flair(user_obj, flair):
    user_id = user_obj['discord_id']
    flairs = user_obj['flair']
    users_collection = db['users']
    index = flairs.index(flair)
    flairs[0], flairs[index] = flairs[index], flairs[0]
    await users_collection.update_one({'discord_id': user_id},
                                      {'$set': {'flair': flairs}})


async def double_xp_24hr(user_id):
    users_collection = db['users']

    user_record = await users_collection.find_one({'discord_id': str(user_id)})
    if user_record:
        current_time = time.time()
        if user_record.get('double_xp', 0) > current_time:
            new_double_xp = user_record['double_xp'] + 86400
        else:
            new_double_xp = current_time + 86400

        r = await users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'double_xp': new_double_xp}})

        return r.acknowledged
    else:
        return False


async def add_double_xp_potion(addr, qty=1):
    users_collection = db['users']
    filter_ = {'address': addr}
    if qty < 0:
        filter_['double_xp_potion'] = {'$gte': abs(qty)}
    r = await users_collection.update_one(filter_, {"$inc": {'double_xp_potion': qty}})
    return r.modified_count == 1


async def apply_lvl_candy(user_id, zerpmon_name):
    zerpmon_collection = db['MoveSets']
    users_collection = db['users']
    user = await users_collection.find_one({'discord_id': str(user_id)})

    old = await zerpmon_collection.find_one({'name': zerpmon_name})
    level = old.get('level', 0)
    ascended = old.get('ascended', False)

    next_lvl = await level_collection.find_one({'level': level + 1}) if (level < 30 or ascended) else None
    user_address = user['address']
    if next_lvl:
        success = await add_lvl_candy(user_address, -1)
        if success:
            await add_xp(zerpmon_name, user_address, next_lvl['xp_required'], ascended=ascended, zerp_obj=old)
            return True
    return False


# choose_gym_zerp()
# MOVES UPDATE QUERY


async def add_equipment(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'equipment': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    await users_collection.update_one({'address': str(address)},
                                      {'$inc': query},
                                      upsert=True)

    return True


async def add_white_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'white_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': str(address)}
    if inc_by < 0:
        filter_['white_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def add_gold_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'gold_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['gold_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)

    return r.modified_count == 1


async def add_purple_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'purple_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['purple_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                          {'$inc': query},
                                          upsert=True)

    return r.acknowledged


async def add_lvl_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'lvl_candy': inc_by}
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['lvl_candy'] = {'$gte': abs(inc_by)}
    if purchased:
        query['zrp_spent'] = amount
    r = await users_collection.update_one(filter_,
                                          {'$inc': query})

    return r.modified_count == 1


async def add_overcharge_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'overcharge_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['overcharge_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def add_gummy_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'gummy_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['gummy_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def add_sour_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'sour_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['sour_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def add_star_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'star_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['star_candy'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def add_jawbreaker(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'jawbreaker': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    filter_ = {'address': address}
    if inc_by < 0:
        filter_['jawbreaker'] = {'$gte': abs(inc_by)}
    r = await users_collection.update_one(filter_,
                                      {'$inc': query},
                                      upsert=True)
    return r.modified_count == 1


async def apply_white_candy(user_id, zerp_name: str, amt=1):
    z_collection = db['MoveSets']
    users_collection = db['users']
    user = await users_collection.find_one({'discord_id': str(user_id)})
    zerp = await z_collection.find_one({'name': zerp_name})
    cnt = zerp.get('white_candy', 0)
    limit = 5 + zerp.get('extra_candy_slot', 0)
    if cnt >= limit or int(user.get('white_candy', 0)) < amt:
        return False
    amt = min(amt, limit - cnt)
    print(amt)

    original_zerp = await db['MoveSets2'].find_one({'name': zerp_name.split(' #')[0]})
    for i, move in enumerate(zerp['moves']):
        if move['color'].lower() == 'white':
            zerp['moves'][i]['dmg'] = round(zerp['moves'][i]['dmg'] + (original_zerp['moves'][i]['dmg'] * (0.02 * amt)),
                                            1)
    del zerp['_id']
    white_candy_usage = cnt
    zerp['white_candy'] = white_candy_usage + amt
    await save_new_zerpmon(zerp)
    await add_white_candy(user['address'], -amt)
    return True


async def apply_gold_candy(user_id, zerp_name, amt=1):
    z_collection = db['MoveSets']
    users_collection = db['users']
    user = await users_collection.find_one({'discord_id': str(user_id)})
    zerp = await z_collection.find_one({'name': zerp_name})
    limit = 5 + zerp.get('extra_candy_slot', 0)
    cnt = zerp.get('gold_candy', 0)
    if cnt >= limit or int(user.get('gold_candy', 0)) < amt:
        return False
    amt = min(amt, limit - cnt)

    original_zerp = await db['MoveSets2'].find_one({'name': zerp_name.split(' #')[0]})
    for i, move in enumerate(zerp['moves']):
        if move['color'].lower() == 'gold':
            zerp['moves'][i]['dmg'] = round(zerp['moves'][i]['dmg'] + original_zerp['moves'][i]['dmg'] * (0.02 * amt),
                                            1)
    del zerp['_id']
    gold_candy_usage = cnt
    zerp['gold_candy'] = gold_candy_usage + amt
    await save_new_zerpmon(zerp)
    await add_gold_candy(user['address'], -amt)
    return True


async def apply_purple_candy(user_id, zerp_name, amt=1):
    z_collection = db['MoveSets']
    users_collection = db['users']
    user = await users_collection.find_one({'discord_id': str(user_id)})
    zerp = await z_collection.find_one({'name': zerp_name})
    limit = 10
    cnt = zerp.get('purple_candy', 0)
    if cnt >= limit or int(user.get('purple_candy', 0)) < amt:
        return False
    amt = min(amt, limit - cnt)
    purple_candy_usage = cnt
    zerp['purple_candy'] = purple_candy_usage + amt
    if zerp['purple_candy'] >= limit:
        # Apply candy effect
        for i, move in enumerate(zerp['moves']):
            if move['color'].lower() == 'purple':
                zerp['moves'][i]['stars'] += 1
    del zerp['_id']
    await save_new_zerpmon(zerp)
    await add_purple_candy(user['address'], -amt)
    return True


async def update_moves(document, save_z=True, effective=False):
    if 'level' in document and document['level'] / 10 >= 1:
        if document['level'] >= 40:
            if int(document.get('number', 0)) < 100000:
                if 'Dragon' in [i['value'] for i in document['attributes'] if
                                i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']:
                    pass
                else:
                    percent_change = 6
                    for i, move in enumerate(document['moves']):
                        if move['color'] == 'blue':
                            move['percent'] = move['percent'] + percent_change
                            document['moves'][i] = move
        else:
            miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
            dec_percent = 3.34 if document['level'] >= 30 else 3.33
            if effective:
                dec_percent = 3.33 * (document['level'] // 10)
                if dec_percent == 9.99:
                    dec_percent = 10
            percent_change = dec_percent if dec_percent < miss_percent else miss_percent
            count = len([i for i in document['moves'] if i['name'] != "" and i['color'] != "blue"]) - 1
            print(document)
            for i, move in enumerate(document['moves']):
                if move['color'] == 'miss':
                    move['percent'] = round(float(move['percent']) - percent_change, 2)
                    document['moves'][i] = move
                elif move['name'] != "" and float(move['percent']) > 0 and move['color'] != "blue":
                    move['percent'] = round(float(move['percent']) + (percent_change / count), 2)
                    document['moves'][i] = move
        if save_z:
            del document['_id']
            await save_new_zerpmon({'moves': document['moves'], 'name': document['name']})

    return document


async def update_zerp_moves_effective(document):
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
    w_candy = document.get('white_candy', 0)
    g_candy = document.get('gold_candy', 0)
    if w_candy > 0:

        original_zerp = await db['MoveSets2'].find_one({'name': document['name'].split(' #')[0]})

        for i, move in enumerate(document['moves']):
            if move['color'].lower() == 'white':
                document['moves'][i]['dmg'] = round(
                    document['moves'][i]['dmg'] + (original_zerp['moves'][i]['dmg'] * 0.02 * w_candy),
                    1)
    if g_candy > 0:
        original_zerp = await db['MoveSets2'].find_one({'name': document['name'].split(' #')[0]})
        for i, move in enumerate(document['moves']):
            if move['color'].lower() == 'gold':
                document['moves'][i]['dmg'] = round(
                    document['moves'][i]['dmg'] + original_zerp['moves'][i]['dmg'] * 0.02 * g_candy,
                    1)
    return document


async def get_trainer_buff_dmg(zerp_name):
    original_zerp = await db['MoveSets2'].find_one({'name': zerp_name.split(' #')[0]})
    extra_dmg_arr = []
    for i, move in enumerate(original_zerp['moves']):
        extra_dmg_arr.append(round(move.get('dmg', 0) * 0.1, 2))
    return extra_dmg_arr


async def get_zrp_stats():
    stats_col = db['stats_log']
    obj = await stats_col.find_one({'name': 'zrp_stats'})
    return obj


async def get_mission_reward_rate():
    stats_col = db['stats_log']
    obj = await stats_col.find_one({'name': 'zrp_stats'})
    return obj.get('mission_xrp_rate')


async def inc_loan_burn(inc):
    stats_col = db['stats_log']

    await stats_col.update_one({
        'name': 'zrp_stats'
    },
        {'$inc': {'loan_burn_amount': inc}}, upsert=True
    )


async def get_loan_burn():
    stats_col = db['stats_log']
    burn_amount = (await stats_col.find_one({'name': 'zrp_stats'})).get('loan_burn_amount', 0)
    return burn_amount


async def get_gym_reset():
    stats_col = db['stats_log']
    res = (await stats_col.find_one({'name': 'zrp_stats'}))
    reset_t = res.get('gym_reset_t', 0)
    if reset_t < time.time() - 120:
        await stats_col.update_one({
            'name': 'zrp_stats'
        },
            {'$set': {'gym_reset_t': (await get_next_ts(3))}}, upsert=True
        )
        return (await get_next_ts(3)), res.get('block_number', 1)
    else:
        return reset_t, res.get('block_number', 1)


async def set_gym_reset():
    stats_col = db['stats_log']
    reset_t = (await stats_col.find_one({'name': 'zrp_stats'})).get('gym_reset_t', 0)
    if reset_t < time.time() + 60:
        reset_t = (await get_next_ts(4)) if reset_t > time.time() else (await get_next_ts(3))
        await stats_col.update_one({
            'name': 'zrp_stats'
        },
            {'$set': {'gym_reset_t': reset_t}}, upsert=True
        )
        config.gym_main_reset = reset_t
    return reset_t


async def update_zrp_stats(burn_amount, distributed_amount, left_amount=None, jackpot_amount=0, db_sep=None):
    stats_col = db['stats_log'] if db_sep is None else db_sep['stats_log']
    query = {'$inc': {'burnt': burn_amount, 'distributed': distributed_amount, 'jackpot_amount': jackpot_amount}}
    if left_amount is not None:
        query['$set'] = {'left_amount': left_amount}
    else:
        query['$inc']['left_amount'] = 0
    print(query)
    await stats_col.update_one({
        'name': 'zrp_stats'
    },
        query, upsert=True
    )


async def set_burnt(burn_amount):
    stats_col = db['stats_log']
    await stats_col.update_one({
        'name': 'zrp_stats'
    },
        {'$set': {'burnt': burn_amount}}, upsert=True
    )


"""BATTLE LOGS"""


async def update_battle_log(user1_id, user2_id, user1_name, user2_name, user1_team, user2_team, winner, battle_type,
                            address1=None):
    battle_log = db['battle_logs']
    bulk_operations = []
    print(f'Updating battle log : {user1_name, user2_name}')
    if user1_id is not None:
        match = {'ts': int(time.time()), 'won': winner == 1, 'opponent': user2_name,
                 'battle_type': battle_type,
                 'data': {'teamA': user1_team, 'teamB': user2_team}}
        extra_q = {}
        if address1:
            extra_q = {'address': address1}
        user1_update = UpdateOne(
            {'discord_id': str(user1_id)},
            {'$push': {'matches': {'$each': [match], '$position': 0, '$slice': 10}},
             '$set': extra_q},
            upsert=True
        )
        bulk_operations.append(user1_update)

    if user2_id is not None:
        match = {'ts': int(time.time()), 'won': winner == 2, 'opponent': user1_name,
                 'battle_type': battle_type,
                 'data': {'teamA': user2_team, 'teamB': user1_team}}
        user2_update = UpdateOne(
            {'discord_id': str(user2_id)},
            {'$push': {'matches': {'$each': [match], '$position': 0, '$slice': 10}}},
            upsert=True
        )
        bulk_operations.append(user2_update)

    print(await battle_log.bulk_write(bulk_operations))


async def get_battle_log(user1_id):
    battle_log = db['battle_logs']
    return await battle_log.find_one({'discord_id': str(user1_id)})


async def log_user_gym(user_id, gym_type, stage=10):
    battle_log = db['battle_logs']
    await battle_log.update_one(
        {'discord_id': str(user_id)},
        {
            '$push': {
                'gym_clear_history': {
                    '$each': [
                        {'time': int(time.time()), 'gym_type': gym_type, 'stage': stage}
                    ],
                    '$slice': -10
                }
            }
        },
        upsert=True
    )


async def log_get_gym_cleared(user_id):
    battle_log = db['battle_logs']
    log = await battle_log.find_one({'discord_id': str(user_id)})
    return log.get('gym_clear_history', None)


"""EQUIPMENT"""


async def set_equipment_on(user_id, equipments, deck_type, deck_no):
    users_collection = db['users']
    user_id = str(user_id)
    equipments = {str(i): eq for i, eq in enumerate(equipments)}
    res = await users_collection.update_one({'discord_id': user_id},
                                            {'$set': {
                                                f'equipment_decks.{deck_type}{"." + deck_no if deck_no is not None else ""}': equipments}},
                                            upsert=True)
    print(res.acknowledged, res.matched_count, res.raw_result)


async def get_eq_by_name(name, gym=False):
    if gym:
        eq1 = await equipment_col.find_one({'type': name}, )
        # Choose a different eq
        eq2 = await equipment_col.aggregate([
        {'$match': {
            'name': {'$ne': eq1['name']},
            '$or': [
                {'type': name},
                {'type': 'Omni'},
            ]}
        },
        {'$sample': {'size': 1}},
        ]).to_list(None)
        return [eq1, eq2[0]]
    else:
        return await equipment_col.find_one({'name': name}, )

async def fix_gym_buffs():
        docs = await db['gym_buffs'].find({'equipment2': 'Tattered Cloak'}).to_list(None)
        for doc in docs:
            await db['gym_buffs'].update_one({'_id': doc['_id']}, {'$set':{'equipment2': 'compatible'}})

# print([i['name'] for i in asyncio.run(get_eq_by_name('Fire', True))])
async def get_all_eqs(limit=None, substr=None, remove_survive=False, remove_random_eq=True):
    if remove_survive:
        q = {
            'effects': {
                '$not': {
                    '$elemMatch': {'type': 'survive-chance'}
                }
            }
        }
    elif remove_random_eq:
        q = {
            'pickRandomEq': {
                '$ne': True
            }
        }
    else:
        q = {}

    if not substr:
        return await equipment_col.find(q, {'_id': 0}).to_list(None)
    else:
        return await equipment_col.find(
            {'name': {'$regex': re.compile(f"^{substr}", re.IGNORECASE)}},
            {'_id': 0, 'name': 1, 'type': 1}) \
            .to_list(25)


"""LOAN"""


async def list_for_loan(zerp, sr, offer, user_id, username, addr, price, active_for, max_days=99999, min_days=3,
                        xrp=True):
    loan_col = db['loan']
    found_in_listing = await loan_col.find_one({'token_id': zerp['token_id'], 'offer': {'$ne': None}})
    if found_in_listing is not None:
        return False
    listing_obj = {
        'serial': sr,
        'zerp_data': zerp,
        'offer': offer,
        'zerp_type': ', '.join([i['value'] for i in zerp['attributes'] if i['trait_type'] == 'Type']),
        'zerpmon_name': zerp['name'],
        'token_id': zerp['token_id'],
        'listed_by': {'id': user_id, 'username': username, 'address': addr},
        'listed_at': time.time() // 1,
        'per_day_cost': price,
        'active_for': active_for,
        'max_days': max_days,
        'min_days': min_days,
        'expires_at': (await get_next_ts(active_for)),
        'xrp': xrp,
        'accepted_by': {'id': None, 'username': None, 'address': None},
        'accepted_on': None,
        'accepted_days': 0,
        'amount_pending': 0,
        'loan_expires_at': None
    }

    res = await loan_col.update_one({'token_id': zerp['token_id']}, {'$set': listing_obj}, upsert=True)
    return res.acknowledged


async def remove_listed_loan(zerp_name_or_id, user_id_or_address, is_id=False, db_sep=None, doubleOffeTo=None):
    loan_col = db['loan'] if db_sep is None else db_sep['loan']
    if not is_id:
        query = {'zerpmon_name': zerp_name_or_id,
                 'loan_expires_at': {'$ne': 0}}
    else:
        query = {'token_id': zerp_name_or_id,
                 'loan_expires_at': {'$ne': 0}}
    if doubleOffeTo:
        r = await loan_col.update_one(query, {'offer': None, 'doubleOffeTo':doubleOffeTo})
    else:
        r = await loan_col.delete_one(query)
    return r.acknowledged


async def update_loanee(zerp, sr, loanee, days, amount_total, loan_ended=False, discord_id='', db_sep=None):
    loan_col = db['loan'] if db_sep is None else db_sep['loan']
    query = {
        'accepted_by': loanee,
        'accepted_on': time.time() // 1 if not loan_ended else None,
        'accepted_days': days,
        'amount_pending': amount_total,
        'loan_expires_at': (await get_next_ts(days)) if days is not None else None
    }
    if loan_ended:
        query['offer'] = None
    res = await loan_col.update_one({'token_id': zerp['token_id']}, {'$set': query}, upsert=True)
    category = zerp.get('category')
    if loan_ended:
        await remove_user_nft(discord_id, sr, trainer=category == 'trainer', equipment=category == 'equipment',
                              db_sep=db_sep)
    else:
        zerp['loaned'] = True
        await add_user_nft(loanee['address'], sr, zerp, trainer=category == 'trainer',
                           equipment=category == 'equipment',
                           db_sep=db_sep)
    return res.acknowledged


async def decrease_loan_pending(nft_id, dec):
    loan_col = db['loan']
    res = await loan_col.update_one({'token_id': nft_id}, {'$inc': {'amount_pending': -dec}})
    return res.acknowledged


async def cancel_loan(token_id):
    loan_col = db['loan']
    res = await loan_col.update_one({'token_id': token_id}, {'$set': {'loan_expires_at': 0}})
    return res.acknowledged


async def get_loaned(user_id=None, zerp_name=None):
    loan_col = db['loan']
    if user_id is not None:
        listings = await loan_col.find({'listed_by.id': user_id}).to_list(None)
        loanee_list = await loan_col.find({'accepted_by.id': user_id, }).to_list(None)
        return [i for i in listings if
                i['zerp_data'].get('category', 'zerpmon') == 'zerpmon'] if listings is not None else [], \
               [i for i in loanee_list if
                i['zerp_data'].get('category', 'zerpmon') == 'zerpmon'] if loanee_list is not None else []
    else:
        listed = await loan_col.find_one({'zerpmon_name': zerp_name})
        return listed


async def get_loan_listings(page_no, docs_per_page=10, search_type='', xrp=None, listed_by='', price=None,
                            zerp_name=''):
    loan_col = db['loan']
    skip_count = (page_no - 1) * docs_per_page
    query = {'offer': {'$ne': None}}
    if search_type:
        query['zerp_type'] = {'$regex': f'.*{search_type}.*', '$options': 'i'}
    if listed_by:
        query['listed_by.id'] = {'$regex': f'.*{listed_by}.*', '$options': 'i'}
    if search_type:
        query['zerpmon_name'] = {'$regex': f'.*{zerp_name}.*', '$options': 'i'}
    if xrp is not None:
        query['xrp'] = xrp
    if price is not None:
        query['per_day_cost'] = {'$lte': price}

    listings = await loan_col.find(query).sort("listed_at", pymongo.DESCENDING).skip(skip_count).limit(
        docs_per_page).to_list(None)
    count = await loan_col.count_documents(query)
    listings = [i for i in listings]
    for document in listings:
        print(document)
    return count, listings


async def set_loaners():
    loan_col = db['loan']
    projection = {
        '_id': 0,  # Exclude the MongoDB document ID
        'listed_by': 1,
        'offer': 1,
        'token_id': 1,
    }
    all_listings = await loan_col.find(projection=projection).to_list(None)
    for listing in all_listings:
        if listing['offer'] is None:
            continue
        if listing['listed_by']['address'] not in config.loaners:
            config.loaners[listing['listed_by']['address']] = [listing['token_id']]
        else:
            config.loaners[listing['listed_by']['address']].append(listing['token_id'])
    print(config.loaners)


async def get_active_loans():
    loan_col = db['loan']
    all_listings = await loan_col.find().to_list(None)
    active = []
    expired = []
    ts = time.time()
    for listing in all_listings:
        if listing['accepted_by']['id'] is not None:
            active.append(listing)
        elif listing['offer'] is None:
            if listing['expires_at'] < ts:
                await remove_listed_loan(listing['token_id'], listing['listed_by']['id'], is_id=True)
            else:
                expired.append(listing)
    return active, expired


"""Backlogging"""


async def save_error_txn(user_address, amount, nft_id, db_sep=None):
    col = db['back_log'] if db_sep is None else db_sep['back_log']
    query = {'$inc': {'amount': amount}}
    if nft_id is not None:
        query['$push'] = {'nft_id': nft_id}
    await col.update_one({'address': user_address}, query, upsert=True)


async def save_br_dict(data):
    col = db['back_log']
    query = {'$set': {'data': data}}
    await col.update_one({'address': '0x0'}, query, upsert=True)


async def get_br_dict():
    col = db['back_log']
    doc = await col.find_one({'address': '0x0'})
    return doc.get('data', []) if doc else []


"""GIFT BOXES"""


async def get_boxes(addr):
    col = db['gift']
    obj = await col.find_one({'address': addr})
    if obj is None:
        return 0, 0
    return obj.get('zerpmon_box', 0), obj.get('xscape_box', 0)


async def dec_box(addr, zerpmon_box: bool, amt=1):
    col = db['gift']
    query = {'$inc': {}}
    if zerpmon_box:
        query['$inc']['zerpmon_box'] = -amt
    else:
        query['$inc']['xscape_box'] = -amt
    await col.update_one({'address': addr}, query)


async def save_token_sent(token_id, to):
    col = db['rewarded_nfts']
    await col.update_one({'nft': token_id}, {'$set': {'nft': token_id, 'to': to}}, upsert=True)


async def remove_token_sent(token_id):
    col = db['rewarded_nfts']
    await col.delete_one({'nft': token_id})


async def remove_mission_nft(nft_to_remove: str):
    result = await db['stats_log'].update_one(
        {'name': 'mission-nfts-bithomp'},
        {'$pull': {'nfts': {'nftokenID': nft_to_remove}}}
    )
    return result.acknowledged if result else None


async def get_all_tokens_sent():
    col = db['rewarded_nfts']
    return [i['nft'] for i in await col.find({}).to_list(None)]


async def save_bought_eq(addr, eq_name):
    col = db['purchase_history_eq']
    await col.update_one({'address': addr}, {'$push': {'bought_eqs': eq_name}}, upsert=True)


async def remove_bought_eq(addr, eq_name):
    col = db['purchase_history_eq']
    await col.update_one(
        {'address': addr},
        {'$pull': {'bought_eqs': {'$eq': eq_name}}},
    )


async def not_bought_eq(addr, eq_name):
    col = db['purchase_history_eq']
    obj = await col.find_one({'address': addr})
    if obj is None:
        return True
    else:
        purchased = obj.get('bought_eqs', [])
        return not (eq_name in purchased)


"""BOSS BATTLE"""


async def get_trainer(nft_id):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for uri in data:
                if nft_id == data[uri]['nftid']:
                    data[uri]['metadata']['token_id'] = nft_id
                    return data[uri]['metadata']
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")


async def get_rand_boss():
    zerpmon_collection = db['MoveSets2']
    random_doc = await zerpmon_collection.find({'name': {'$regex': 'Titan'}}).to_list(None)
    return random.choice([i for i in random_doc])


async def get_boss_reset(hp) -> [bool, int, int, int, bool]:
    stats_col = db['stats_log']
    obj = await stats_col.find_one({'name': 'world_boss'})
    if obj is None:
        obj = {}
    reset_t = obj.get('boss_reset_t', 0)
    msg_id = obj.get('boss_msg_id', None) if obj.get('boss_msg_id', None) else config.BOSS_MSG_ID
    if not obj or (reset_t < time.time()):
        n_t = int(await get_next_ts(7))
        active = hp > 0
        boss = await get_rand_boss()
        trainer = await get_trainer('0008138805D83B701191193A067C4011056D3DEE2B298C553C7172B400000019')
        del boss['_id']
        boss_alive = obj.get('boss_active', False)
        if boss_alive:
            penalty = 5 * hp / 100
            penalty_hp = penalty + obj.get('penalty_hp', 0)
            penalty_week = 1 + obj.get('penalty_week', 0)
        else:
            penalty_hp, penalty_week = 0, 0
        await stats_col.update_one({
            'name': 'world_boss'
        },
            {'$set': {'boss_reset_t': n_t, 'boss_active': active, 'boss_hp': hp - penalty_hp, 'boss_zerpmon': boss,
                      'boss_trainer': trainer,
                      'boss_eq': random.choice(await get_all_eqs(remove_survive=True)).get('name'),
                      "reward": 500 if not boss_alive else obj['reward'] + 300,
                      'start_hp': hp, 'boss_msg_id': msg_id,
                      'total_weekly_dmg': 0 if not obj.get('boss_active', False) else obj['total_weekly_dmg'],
                      'penalty_hp': penalty_hp,
                      'penalty_week': penalty_week
                      }
             }, upsert=True
        )
        return active, hp, n_t, msg_id, True
    else:
        return obj.get('boss_active'), obj.get('boss_hp'), reset_t, msg_id, False


async def get_boss_stats():
    stats_col = db['stats_log']
    obj = await stats_col.find_one({'name': 'world_boss'})
    return obj


async def set_boss_battle_t(user_id, reset_next_t=False) -> None:
    users_col = db['users']
    await users_col.update_one({'discord_id': str(user_id)},
                               {'$set': {'boss_battle_stats.next_battle_t': (
                                                                                await get_next_ts()) + 60 if not reset_next_t else 0}})


async def add_boss_txn_log(uid: str, user_data: dict, amount: float, dmgDealt, startHp):
    txn_log_col = db['general-txn-queue']
    to_addr = user_data['address']
    res = await txn_log_col.update_one({'uniqueId': uid + f'-{int(await get_next_ts()) + 60}'},
                                       {'$setOnInsert': {
                                           'type': 'Payment',
                                           'from': 'boss',
                                           'destination': to_addr,
                                           'amount': amount,
                                           'currency': 'ZRP',
                                           'status': 'pending',
                                           'dmgDealt': dmgDealt,
                                           'startHp': startHp,
                                           'destinationTag': user_data.get('destination_tag')
                                       }}, upsert=True)
    return res.acknowledged


async def set_boss_hp(user_id, dmg_done, cur_hp) -> None:
    users_col = db['users']
    await users_col.update_one({'discord_id': str(user_id)},
                               {'$inc': {'boss_battle_stats.weekly_dmg': dmg_done,
                                         'boss_battle_stats.total_dmg': dmg_done},
                                '$max': {'boss_battle_stats.max_dmg': dmg_done}},
                               )
    stats_col = db['stats_log']
    new_hp = cur_hp - dmg_done
    if new_hp > 0:
        await stats_col.update_one({'name': 'world_boss'},
                                   {'$inc': {'total_weekly_dmg': dmg_done, 'boss_hp': -dmg_done}})
    else:
        await stats_col.update_one({'name': 'world_boss'}, {'$set': {'boss_hp': 0, 'boss_active': False}})


async def set_boss_msg_id(msg_id) -> None:
    stats_col = db['stats_log']
    await stats_col.update_one({'name': 'world_boss'}, {'$set': {'boss_msg_id': msg_id}})


async def reset_weekly_dmg() -> None:
    users_col = db['users']
    await users_col.update_many({'boss_battle_stats': {'$exists': True}},
                                {'$set': {'boss_battle_stats.weekly_dmg': 0}})
    stats_col = db['stats_log']
    await stats_col.update_one({'name': 'world_boss'}, {'$set': {'total_weekly_dmg': 0, 'boss_active': False}})


async def boss_reward_winners() -> list:
    users_col = db['users']

    filter = {"boss_battle_stats": {"$exists": True}}
    projection = {"boss_battle_stats": 1, "address": 1, "discord_id": 1, "username": 1, '_id': 0}
    li = await users_col.find(filter, projection).to_list(None)

    return [i for i in li]


async def get_boss_leaderboard():
    users_collection = db['users']
    filter = {'boss_battle_stats': {'$exists': True}}
    projection = {"boss_battle_stats": 1, "address": 1, "discord_id": 1, "username": 1, '_id': 0}
    top_users = [i for i in await users_collection.find(filter, projection).sort('boss_battle_stats.weekly_dmg',
                                                                                 DESCENDING).to_list(None)]
    top_10 = []
    for i in range(10):
        if i < len(top_users):
            top_10.append(top_users[i])
    return top_10


"""Store V2 item functions"""


async def verify_zerp_flairs():
    stats_col = db['store_items']
    flair_doc = await stats_col.find_one({'name': 'Zerpmon Flair'})
    if flair_doc is None:
        await stats_col.update_one({'name': 'Zerpmon Flair'}, {'variants': [i for i in config.ZERPMON_FLAIRS]},
                                   upsert=True)


async def get_available_zerp_flairs(reverse=False):
    stats_col = db['store_items']
    return {i: j for i, j in (await stats_col.find_one({'name': 'Zerpmon Flair'})).get('variants', []).items() if
            (j is None and not reverse) or (j is not None and reverse)}


async def add_zerp_flair(user_id, flair_name):
    users_collection = db['users']
    stats_col = db['store_items']
    user_id = str(user_id)
    await users_collection.update_one({'discord_id': user_id},
                                      {'$set': {f'z_flair.{flair_name}': None}})
    r = await stats_col.update_one({'name': 'Zerpmon Flair'}, {"$pull": {f'variants': flair_name, }})
    return r.acknowledged


async def update_zerp_flair(discord_id, zerp_name, old_zerp_name, flair_name):
    users_collection = db['users']
    zerpmon_collection = db['MoveSets']

    r = await users_collection.update_one({'discord_id': discord_id},
                                          {'$set': {f'z_flair.{flair_name}': zerp_name}})
    if old_zerp_name:
        await zerpmon_collection.update_one({'name': old_zerp_name}, {'$unset': {'z_flair': ""}})
    await zerpmon_collection.update_one({'name': zerp_name}, {'$set': {'z_flair': flair_name}})
    return r.acknowledged


async def add_zerp_lure(user_addr, qty=1):
    users_collection = db['users']
    filter_ = {'address': user_addr}
    if qty < 0:
        filter_['lure_cnt'] = {'$gte': qty}
    r = await users_collection.update_one(filter_,
                                          {'$inc': {'lure_cnt': qty}})
    return r.modified_count > 0


async def update_user_zerp_lure(user_id, lure_type):
    users_collection = db['users']
    user_id = str(user_id)
    lure_value = {
        'expire_ts': int(time.time() + 86400),
        'type': lure_type
    }
    await users_collection.update_one({'discord_id': user_id},
                                      {'$set': {'zerp_lure': lure_value}})


async def apply_candy_24(user_id, addr, zerp_name, candy_type):
    candy_collection = db['active_candy_stats']
    zerpmon_collection = db['MoveSets']
    user_id = str(user_id)
    exp_ts = int(time.time() + 86400)
    zerp_value = {
        'expire_ts': exp_ts,
        'type': candy_type
    }
    adder_fn = globals().get(f'add_{candy_type}')
    query = {'$set': {f'active.{zerp_name}.{"type1" if candy_type == "overcharge_candy" else "type2"}': zerp_value}}
    r = await candy_collection.update_one({'discord_id': user_id},
                                          query, upsert=True)
    await adder_fn(addr, -1)
    await zerpmon_collection.update_one({'name': zerp_name}, {'$set': {candy_type: exp_ts}})
    return r.acknowledged


async def get_active_candies(user_id):
    candy_collection = db['active_candy_stats']
    doc = await candy_collection.find_one({'discord_id': str(user_id)})
    return doc.get('active', {}) if doc else {}


async def update_stats_candy(doc, candy_type):
    old_p = [(i.get('percent', None) if i['color'] != 'blue' else None) for i in doc['moves']]
    if candy_type == 'overcharge_candy':
        new_p = await battle_effect.update_array(old_p, 7, -10, own=True)
        for i, move in enumerate(doc['moves']):
            if move['color'] == 'blue':
                continue
            if move.get('dmg', None):
                move['dmg'] = round(move['dmg'] * 1.25, 2)
            move['percent'] = new_p[i]
    else:
        match candy_type:
            case 'gummy_candy':
                new_p = await battle_effect.update_array(old_p, 0, 10, own=True, index2=1)
                for i, move in enumerate(doc['moves']):
                    if move['color'] == 'blue':
                        continue
                    move['percent'] = new_p[i]
            case 'sour_candy':
                new_p = await battle_effect.update_array(old_p, 2, 10, own=True, index2=3)
                for i, move in enumerate(doc['moves']):
                    if move['color'] == 'blue':
                        continue
                    move['percent'] = new_p[i]
            case 'star_candy':
                new_p = await battle_effect.update_array(old_p, 4, 10, own=True, index2=5)
                print(sum([i for i in new_p if i]))
                for i, move in enumerate(doc['moves']):
                    if move['color'] == 'blue':
                        continue
                    move['percent'] = new_p[i]
            case 'jawbreaker':
                for i, move in enumerate(doc['moves']):
                    if move['color'] == 'blue':
                        move['percent'] += 15


"""ascend fn"""


async def ascend_zerpmon(addr, zerp_name):
    zerpmon_collection = db['MoveSets']
    users_collection = db['users']
    result = await zerpmon_collection.update_one({"name": zerp_name}, {'$set': {'ascended': True}})

    await users_collection.update_one({'address': addr},
                                      {'$inc': {'revive_potion': 10, 'mission_potion': 10}})

    return result.acknowledged


"""Recycle"""


async def get_higher_lvls(lvl=1):
    res = await level_collection.find({'level': {'$gt': lvl}}).sort('level', pymongo.ASCENDING).to_list(None)

    return res


async def remove_nft_from_safari_stat(nft_id) -> None:
    stats_col = db['stats_log']
    await stats_col.update_one({'name': 'safari-nfts-bithomp'}, {'$pull': {'nfts': {'nftokenID': nft_id}}})


async def get_safari_nfts():
    stats_col = db['stats_log']
    return (await stats_col.find_one({'name': 'safari-nfts-bithomp'})).get('nfts', [])


async def remove_nft_from_mission_stat(nft_id) -> None:
    stats_col = db['stats_log']
    await stats_col.update_one({'name': 'mission-nfts-bithomp'}, {'$pull': {'nfts': {'nftokenID': nft_id}}})


async def get_mission_nfts():
    stats_col = db['stats_log']
    return (await stats_col.find_one({'name': 'mission-nfts-bithomp'})).get('nfts', [])


async def add_xrp_txn_log(uid: str, from_addr: str, user_data: dict, amount: float, xp: int, candy=None):
    txn_log_col = db['mission-txn-queue']
    to_addr = user_data['address']
    res = await txn_log_col.update_one({'uid': to_addr + uid},
                                       {'$setOnInsert': {
                                           'type': 'Payment',
                                           'from': from_addr,
                                           'destination': to_addr,
                                           'amount': amount,
                                           'currency': 'XRP',
                                           'status': 'pending' if (amount > 0 or candy) else 'fulfilled',
                                           'xp': xp,
                                           'candy': candy,
                                           'destinationTag': user_data.get('destination_tag')
                                       }}, upsert=True)
    return res.acknowledged


async def add_zrp_txn_log(from_addr: str, to_addr: str, amount: float, destination_tag: int | None):
    txn_log_col = db['safari-txn-queue']
    res = await txn_log_col.insert_one({
        'type': 'Payment',
        'from': from_addr,
        'destination': to_addr,
        'amount': amount,
        'currency': 'ZRP',
        'status': 'pending',
        'destinationTag': destination_tag,
    })
    return res.acknowledged


async def add_nft_txn_log(from_addr: str, to_addr: str, nft_id: float, is_eq: bool, issuer: str, uri: str, sr,
                          is_safari=True, uid=None):
    txn_log_col = db['safari-txn-queue' if is_safari else 'mission-txn-queue']
    doc = {
        'type': 'NFTokenCreateOffer',
        'destination': to_addr,
        'from': from_addr,
        'isEquipment': is_eq,
        'nftokenID': nft_id,
        'nftSerial': sr,
        'issuer': issuer,
        'uri': uri,
        'status': 'pending',
        'offerID': None,
    }
    if not is_safari and uid:
        doc['uid'] = to_addr + uid
        res = await txn_log_col.update_one({'uid': 'nft' + uid},
                                           {
                                               '$setOnInsert': doc
                                           }, upsert=True)
    else:
        res = await txn_log_col.insert_one(doc)
    return res.acknowledged


"""Gym tower"""


async def get_random_trainers(limit=5):
    collection = db['trainers']

    random_documents = await collection.aggregate([
        {'$match': {'legend_gryll': {'$exists': False}}},
        {'$sample': {'size': limit}},
        {'$project': {'_id': 0, 'image': 1, 'name': 1, 'type': 1, 'nft_id': 1, 'trainer number': 1, 'affinity': 1}}
    ]).to_list(None)

    if random_documents:
        return list(random_documents)
    else:
        return None


async def get_temp_user(user_id: str, autoc=False):
    temp_users_col = db['temp_user_data']
    if not autoc:
        return await temp_users_col.find_one({'discord_id': user_id})
    else:
        pipeline = [{'$match': {'discord_id': user_id}},
                    {
                        '$project': {
                            '_id': 0,
                            'zerpmons': {
                                '$map': {
                                    'input': '$zerpmons',
                                    'as': 'zerpmon',
                                    'in': {
                                        'name': '$$zerpmon.name',
                                        'attributes': '$$zerpmon.attributes'
                                    }
                                }
                            },
                            'trainers': {
                                '$map': {
                                    'input': '$trainers',
                                    'as': 'trainer',
                                    'in': {
                                        'name': '$$trainer.name',
                                        'type': '$$trainer.type',
                                        'affinity': '$$trainer.affinity'
                                    }
                                }
                            },
                            'equipments': {
                                '$map': {
                                    'input': '$equipments',
                                    'as': 'equipment',
                                    'in': {
                                        'name': '$$equipment.name',
                                        'type': '$$equipment.type',
                                    }
                                }
                            }
                        }
                    }
                    ]
        res = list(await temp_users_col.aggregate(pipeline).to_list(None))[0]
        for idx in range(len(res['zerpmons'])):
            i = res['zerpmons'][idx]
            res['zerpmons'][idx] = {'name': i['name'],
                                    'type': [_i['value'] for _i in i['attributes'] if _i['trait_type'] == 'Type']}
        return res


# print(asyncio.run(get_owned('1017889758313197658', autoc=True)))

async def add_temp_user(user_d, fee_paid=True, is_reset=False, is_free_mode=False):
    temp_users_col = db['temp_user_data']
    user_id, username, user_addr = user_d['discord_id'], user_d['username'], user_d['address']

    eq_deck = {}
    for i in range(5):
        eq_deck[str(i)] = {str(i): None for i in range(5)}
    user_doc = {'username': username,
                'address': user_addr,
                'fee_paid': fee_paid,
                'zerpmons': await get_random_doc_with_type(limit=10, level=30),
                'equipments': random.sample(await get_all_eqs(remove_random_eq=True), 10),
                'trainers': await get_random_trainers(10),
                "battle_deck": {'0': {}},
                "equipment_decks": eq_deck,
                'reset': False,
                }
    if not is_reset:
        if 'flair' in user_d:
            user_doc['flair'] = user_d['flair']
        if 'profile_photo_url' in user_d:
            user_doc['profile_photo_url'] = user_d['profile_photo_url']
        if 'display_name' in user_d:
            user_doc['display_name'] = user_d['display_name']
        user_doc['tower_level'] = 1
        user_doc['lives'] = 1
        user_doc['gym_order'] = random.sample(config_extra.TOWER_SEQ[:-1], 19)
        user_doc['gym_order'].append('Dragon')
        user_doc['is_free_mode'] = is_free_mode
    obj = await temp_users_col.find_one_and_update({'discord_id': user_id},
                                                   {'$set': user_doc, }, upsert=True,
                                                   return_document=ReturnDocument.AFTER)
    return obj


async def update_gym_tower_deck(deck_no, new_deck, eqs, user_id):
    users_collection = db['temp_user_data']

    doc = await users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else \
        doc["battle_deck"]

    arr['0'] = new_deck
    r = await users_collection.update_one({'discord_id': str(user_id)},
                                          {"$set": {f'equipment_decks.0': eqs,
                                                    'battle_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


async def reset_gym_tower(user_id, zrp_earned=0, lvl=1, is_free_mode=False):
    users_collection = db['temp_user_data']
    eq_deck = {}
    for i in range(5):
        eq_deck[str(i)] = {str(i): None for i in range(5)}
    res = await users_collection.update_one({'discord_id': str(user_id)},
                                            {'$set': {'fee_paid': False,
                                                      "battle_deck": {'0': {}},
                                                      "equipment_decks": eq_deck,
                                                      'zerpmons': [],
                                                      'equipments': [],
                                                      'trainers': [],

                                                      },
                                             '$max': {'max_level': lvl},
                                             '$inc': {'total_zrp_earned': zrp_earned,
                                                      'tp': 0 if is_free_mode else (lvl - 1),
                                                      'total_matches': 1}})
    return res.acknowledged


async def dec_life_gym_tower(user_id):
    users_collection = db['temp_user_data']

    eq_deck = {}
    for i in range(5):
        eq_deck[str(i)] = {str(i): None for i in range(5)}

    q = {'reset': True,
         "battle_deck": {'0': {}},
         "equipment_decks": eq_deck,
         'zerpmons': [],
         'equipments': [],
         'trainers': [],
         'lives': 0
         }
    res = await users_collection.update_one({'discord_id': str(user_id)},
                                            {'$set': q, '$inc': {'total_matches': 1}})
    return res.acknowledged


async def update_gym_tower(user_id, new_level, zrp_earned=0, is_free_mode=False):
    users_collection = db['temp_user_data']
    eq_deck = {}
    for i in range(5):
        eq_deck[str(i)] = {str(i): None for i in range(5)}
    if new_level > 20:
        q = {'tower_level': 1, 'fee_paid': False, 'zerpmons': [],
             'equipments': [],
             'trainers': [], }
        inc_q = {
            'total_matches': 1,
            'total_zrp_earned': zrp_earned,
            'tp': 0 if is_free_mode else (new_level - 1),
        }
    else:
        q = {'tower_level': new_level, 'reset': True,
             "battle_deck": {'0': {}},
             "equipment_decks": eq_deck,
             'zerpmons': [],
             'equipments': [],
             'trainers': [],
             }
        inc_q = {
            'total_matches': 1
        }
    res = await users_collection.update_one({'discord_id': str(user_id)},
                                            {'$set': q,
                                             '$inc': inc_q
                                             })
    return res.acknowledged


async def get_tower_rush_leaderboard(discord_id):
    users_collection = db['temp_user_data']
    filter_ = {'tp': {'$exists': True}}
    projection = {"tp": 1, "address": 1, "discord_id": 1, "username": 1, "total_zrp_earned": 1, 'max_level': 1,
                  '_id': 0}

    cursor = users_collection.find(filter_, projection).sort('tp', DESCENDING)
    top_10 = list(enumerate(await cursor.to_list(length=None), start=1))
    if discord_id:
        # Find the user's rank and return the top 10 users or less
        user_rank = next((rank for rank, user in top_10 if user['discord_id'] == discord_id), None)
        top_10 = top_10[:10]

        # Append the user's rank to the result
        if user_rank and user_rank > top_10[-1][0]:
            top_10.append((user_rank, await users_collection.find_one({'discord_id': discord_id}, projection)))

    return top_10 if len(top_10) <= 10 else top_10[:10]


# Crossmark fn

async def save_sign_up_req(user_id: str, uuid: str) -> bool:
    req_collection = db['signin_requests']
    res = await req_collection.update_one({'discord_id': user_id},
                                          {'$set': {'uuid': uuid, 'status': 'pending', 'address': ''}}, upsert=True)
    return res.acknowledged


async def get_req_status(uuid: str) -> (bool, str):
    req_collection = db['signin_requests']
    res = await req_collection.find_one({'uuid': uuid})
    success = res['status'] == 'fulfilled'
    if success:
        await req_collection.delete_one({'uuid': uuid})
    addr = res['address']
    return success, addr


async def del_sign_up_req(uuid: str) -> bool:
    req_collection = db['signin_requests']
    res = await req_collection.delete_one({'uuid': uuid})
    return res.acknowledged


async def insert_free_mode_stats():
    stats_col = db['stats_log']
    doc = {
        'name': 'free_mode',
        'playerAAddress': 'r9cKrPx9uNZJBUPFZpC6Qf7WHmMSfPsFHM',
        'playerBAddress': 'r3rny1bdHoTaELWe3HCULQranbhvqfbjEy',
        'playerAInQueue': False,
        'playerBInQueue': False,
        'playerAZerpmons': None,
        'playerAEquipments': None,
        'playerATrainer': None,
        'playerBZerpmons': None,
        'playerBEquipments': None,
        'playerBTrainer': None,
        'lastBattleId': None,
    }
    obj = await stats_col.update_one({'name': 'free_mode'}, {'$set': doc}, upsert=True)


# async def test(is_gym_reset):
#     all_users = await get_all_users()
#     for user in all_users:
#         try:
#             if 'gym' in user:
#                 won_gyms = user['gym'].get('won', {})
#                 for gym, obj in won_gyms.items():
#                     if obj['next_battle_t'] < time.time() - 86300:
#                         await reset_gym(user['discord_id'], user['gym'], gym, lost=False, skipped=True,
#                                                  reset=is_gym_reset)
#                     else:
#                         await reset_gym(user['discord_id'], user['gym'], gym, lost=False, reset=is_gym_reset)
#         except:
#             logging.error(f'USER OBJ ERROR: {traceback.format_exc()}')
# asyncio.run(test(True))

async def make_battle_req(zerp_arr1, zerp_arr2, tc1, tc2, battle_type='mission', extraB=None, startHp=None, is_br=False):
    input_col = db['discord_battle_requests']
    isValidXbladeGame = battle_type != 'tower'
    obj = {
        'uid': str(uuid.uuid4()),
        'playerAZerpmons': [],
        'playerBZerpmons': [],
        'playerAEquipments': [],
        'playerBEquipments': [],
        'playerATrainer': tc1,
        'playerBTrainer': tc2,
        'battleType': battle_type,
        'status': 'pending',
        'extrabuff': extraB,
        'startHp': startHp,
    }
    xbladesIds = []
    for i in zerp_arr1:
        obj['playerAZerpmons'].append(i['name'])
        obj['playerAEquipments'].append(i.get('buff_eq'))
        if isValidXbladeGame and i.get('buff_eq') == 'Xblade' and i.get('eq_id'):
            xbladesIds.append(i.get('eq_id'))
    for i in zerp_arr2:
        obj['playerBZerpmons'].append(i['name'])
        obj['playerBEquipments'].append(i.get('buff_eq'))
        if isValidXbladeGame and i.get('buff_eq') == 'Xblade' and i.get('eq_id'):
            xbladesIds.append(i.get('eq_id'))
    if len(xbladesIds) > 0:
        await db['equipment_hosted_metadata'].update_many({
            'token_id':{'$in': xbladesIds}
        },
            {
                '$inc': {'game_count': 1}
            }
        )

    input_col.insert_one(obj)
    config.battle_results[obj['uid']] = None
    return obj['uid']


async def make_sim_battle_req(playerA, playerB, battle_type='simulation', cnt=1):
    input_col = db['discord_battle_requests']
    obj = {
        'uid': str(uuid.uuid4()),
        'playerAZerpmons': [],
        'playerBZerpmons': [],
        'playerAEquipments': [],
        'playerBEquipments': [],
        'playerATrainer': playerA['trainer'] if playerA['trainer'] else None,
        'playerBTrainer': playerB['trainer'] if playerB['trainer'] else None,
        'battleType': battle_type,
        'status': 'pending',
        'cnt': cnt,
        'extrabuff': None,
        'startHp': None,
    }
    for idx, item in enumerate(playerA['zerpmons']):
        if item:
            obj['playerAZerpmons'].append(item)
            if playerA['equipments'][idx]:
                obj['playerAEquipments'].append(playerA['equipments'][idx])
            else:
                obj['playerAEquipments'].append(None)
    for idx, item in enumerate(playerB['zerpmons']):
        if item:
            obj['playerBZerpmons'].append(item)
            if playerB['equipments'][idx]:
                obj['playerBEquipments'].append(playerB['equipments'][idx])
            else:
                obj['playerBEquipments'].append(None)
    input_col.insert_one(obj)
    for idx in range(cnt):
        config.battle_results[obj['uid'] + f'{idx}'] = None
    return obj['uid']


async def retrieve_battle_results():
    output_col = db['discord_battle_results']
    res = await output_col.find({}).to_list(None)
    return res if res else []


async def delete_battle_results(batch_uids):
    output_col = db['discord_battle_results']
    res = await output_col.delete_many({'uid': {'$in': batch_uids}})
    return res.acknowledged


async def insert_event(event):
    return await db['events'].update_one(
        {'code': event['code']},
        {
            '$set': event
        }, upsert=True
    )


async def delete_event(code):
    return await db['events'].delete_one(
        {'code': code}
    )


async def get_events(substr):
    return await db['events'].find(
        {'name': {'$regex': re.compile(f"^{substr}", re.IGNORECASE)}},
        projection={
            '_id': 0,
            'name': 1,
            'code': 1,
            'title': 1
        }
    ).to_list(None)


async def ban_user_and_nfts(user_addr, is_id=False):
    users_collection = db['users']
    q = {'discord_id': user_addr} if is_id else {'address': user_addr}
    ts = int(time.time())
    user = await users_collection.find_one_and_update(q, {'$set': {'punished': True, 'punished_at': ts}},
                                                      return_document=ReturnDocument.AFTER)
    # Ban all nfts

    # Zerpmon
    zerpmon_list = [i['name'] for k, i in user['zerpmons'].items()]
    update_query = {f'moves.{i}.percent': (0 if i < 7 else 100) for i in range(8)}
    update_query['punished'] = True
    update_query['punished_at'] = ts
    res = await db['MoveSets'].update_many({
        'name': {'$in': zerpmon_list},
    },
        {
            '$set': update_query
        }
    )
    # Trainer & Equipment (not active rn)
    # trainer_list = [i['token_id'] for k, i in user['trainer_cards'].items()]
    # eq_list = [i['token_id'] for k, i in user['equipments'].items()]
    # await db['punished_nfts'].insert_many([{
    #     'address': user['address'],
    #     'nft_id': i,
    #     'ban_ts': ts,
    #     'category': 'trainer'
    # } for i in trainer_list])
    # await db['punished_nfts'].insert_many([{
    #     'address': user['address'],
    #     'nft_id': i,
    #     'ban_ts': ts,
    #     'category': 'equipment'
    # } for i in eq_list])
    return res.acknowledged


async def unban_user_and_nfts(user_addr, is_id=False):
    users_collection = db['users']
    q = {'discord_id': user_addr} if is_id else {'address': user_addr}
    user = await users_collection.find_one_and_update(q, {'$set': {'punished': False}},
                                                      return_document=ReturnDocument.AFTER)
    # Unban all nfts
    # Zerpmon
    zerpmon_collection = db['MoveSets']
    zerpmon_list = [i['name'] for k, i in user['zerpmons'].items()]
    zerpmon_name_lvl = await zerpmon_collection.find({'name': {'$in': zerpmon_list}},
                                                     projection={
                                                         '_id': 0,
                                                         'level': 1,
                                                         'name': 1,
                                                         'white_candy': 1,
                                                         'gold_candy': 1,
                                                     }).to_list(None)
    for zerpmon in zerpmon_name_lvl:
        zerpmon_base = await get_zerpmon(zerpmon['name'], mission=True)
        zerpmon_base['level'] = zerpmon['level']
        zerpmon_base['white_candy'] = zerpmon.get('white_candy', 0)
        zerpmon_base['gold_candy'] = zerpmon.get('gold_candy', 0)
        zerpmon_updated = await update_zerp_moves_effective(zerpmon_base)
        await zerpmon_collection.update_one({'name': zerpmon['name']},
                                            {'$set': {'moves': zerpmon_updated['moves'], 'punished': False}})

    # Trainer & Equipment
    # trainer_list = [i['token_id'] for k, i in user['trainer_cards'].items()]
    # eq_list = [i['token_id'] for k, i in user['equipments'].items()]
    # await db['punished_nfts'].delete_many({
    #     'nft_id': {'$in': trainer_list}
    # })
    # await db['punished_nfts'].delete_many({
    #     'nft_id': {'$in': eq_list}
    # })
    return True


async def unban_nft(nft_id):
    zerpmon_collection = db['MoveSets']
    zerpmon = await zerpmon_collection.find_one({'nft_id': nft_id},
                                                projection={
                                                    '_id': 0,
                                                    'level': 1,
                                                    'white_candy': 1,
                                                    'gold_candy': 1,
                                                })
    zerpmon_base = await db['MoveSets2'].find_one({'nft_id': nft_id})
    zerpmon_base['level'] = zerpmon['level']
    zerpmon_base['white_candy'] = zerpmon.get('white_candy', 0)
    zerpmon_base['gold_candy'] = zerpmon.get('gold_candy', 0)
    zerpmon_updated = await update_zerp_moves_effective(zerpmon_base)
    r = await zerpmon_collection.update_one({'nft_id': nft_id},
                                            {'$set': {'moves': zerpmon_updated['moves'], 'punished': False}})
    return r.acknowledged


async def check_banned(user_addr, is_id=False):
    users_collection = db['users']
    q = {'discord_id': user_addr, 'punished': True} if is_id else {'address': user_addr, 'punished': True}
    user = await users_collection.find_one(q, projection={'_id': 0, 'address': 1})
    return user is not None


async def change_stream_listener():
    inner_client = AsyncIOMotorClient(config.MONGO_URL)
    _db = inner_client['Zerpmon']
    pipeline = [{'$match': {'operationType': 'insert'}}]
    resume_token = None
    while True:
        try:
            async with _db['loan-payments'].watch(pipeline, resume_after=resume_token) as stream:
                stream: AsyncIOMotorChangeStream = stream
                async for insert_change in stream:
                    try:
                        print(insert_change)
                        doc = insert_change['fullDocument']
                        addr = doc['payerAddress']
                        data = {
                            'uid': str(doc['_id']),
                            'XRP': {'amount': round(doc['XRPAmount'], 2),
                                    'paid': True if doc['XRPAmount'] == 0 else False},
                            'ZRP': {'amount': round(doc['ZRPAmount'], 2), 'paid': False},
                            'checked': False,
                        }
                        config_extra.loan_payments[addr] = data
                        print(config_extra.loan_payments)
                        resume_token = stream.resume_token
                    except:
                        print(traceback.format_exc())
        except:
            print(traceback.format_exc())
            if resume_token is None:
                print('...')


async def get_world_boss_reward_message():
    stats_col = db['stats_log']
    res = await stats_col.find_one_and_update({'name': 'world_boss_reward_log'},
                                              {'$set': {'name': 'world_boss_reward_log_old'}})
    if res:
        return True, res
    else:
        return False, res


async def send_user_notification(content_list, addr, _id, ):
    notification_list = []
    for content in content_list:
        user_notification = {
            'userId': _id,
            'userAddress': addr,
            'read': False,
            'uniqueId': str(uuid.uuid4()),
            'notification': {
                'icon': '',
                'title': content['title'],
                'body': content['body'],
                'url': content['url'],
            },
            'category': 'general',
            'timestamp': int(time.time() * 1000),
            'sendOn': int(time.time() * 1000)
        }
        notification_list.append(user_notification)

    add_to_user_notification_queue_promise = db['user-notifications-queue'].insert_many(notification_list)
    add_to_in_app_user_notifications_promise = db['user-notifications'].insert_many(notification_list)

    await asyncio.gather(add_to_user_notification_queue_promise, add_to_in_app_user_notifications_promise)


async def get_custodial_wallet_user_balance(tag: int, currency: str) -> float:
    custodial_wallet_address = config_extra.CUSTODIAL_ADDR

    pipeline = [
        {
            "$match": {
                "$or": [
                    {
                        "destinationAddress": custodial_wallet_address,
                        "destinationTag": tag,
                        "currency": {"$regex": currency, "$options": "i"},
                    },
                    {
                        "sourceAddress": custodial_wallet_address,
                        "sourceTag": tag,
                        "currency": {"$regex": currency, "$options": "i"},
                    },
                ]
            }
        },
        {
            "$group": {
                "_id": None,
                "balance": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$eq": ["$destinationAddress", custodial_wallet_address]},
                                    {"$eq": ["$destinationTag", tag]},
                                ]
                            },
                            "$amount",
                            {"$multiply": ["$amount", -1]},
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "balance": 1,
            }
        },
    ]

    result = await db['custodial-wallet-payments'].aggregate(pipeline).to_list(length=None)

    balance = result[0]['balance'] if len(result) > 0 else 0
    fixed_balance = round(float(balance), 6)
    return fixed_balance


async def get_pending_user_withdrawals_amount(tag: int, currency: str) -> float:
    pipeline = [
        {
            "$match": {
                "userTag": tag,
                "currency": {"$regex": currency, "$options": "i"},
                "status": "pending",
            }
        },
        {
            "$group": {
                "_id": None,
                "balance": {"$sum": "$amount"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "balance": 1,
            }
        },
    ]

    result = await db['custodial-wallet-withdrawal-requests'].aggregate(pipeline).to_list(length=None)

    balance = result[0]['balance'] if len(result) > 0 else 0
    fixed_balance = round(float(balance), 6)
    return fixed_balance


async def get_pending_user_withdrawals_count(tag: int) -> int:
    count = await db['custodial-wallet-withdrawal-requests'].count_documents({
        'userTag': tag,
        'status': 'pending',
    })

    return count


async def add_user_tip_txn(currency:str, amt:float, source_tag:int, recv_destination_tag:int):
    doc = {
        "transactionId": f"USER-TIP-{str(uuid.uuid4())}",
        "amount": amt,
        "currency": currency,
        "destinationAddress": "rUNEer3ptfFXnrenuaspvoZ1KsSgvnCpj5",
        "destinationTag": recv_destination_tag,
        "sourceAddress": "rUNEer3ptfFXnrenuaspvoZ1KsSgvnCpj5",
        "sourceTag": source_tag,
        "timestamp": int(time.time() * 1000)
    }
    bal, withdrawal_req_cnt = await asyncio.gather(get_custodial_wallet_user_balance(source_tag, currency),
                                                   get_pending_user_withdrawals_count(source_tag))
    if withdrawal_req_cnt > 0:
        return False, "**Failed** trying to tip when a withdrawal request is in queue"
    if bal < amt:
        return False, "**Failed** tip amount more than **ZerpWallet** balance"
    await db['custodial-wallet-payments'].insert_one(doc)
    withdrawal_req_cnt = await get_pending_user_withdrawals_count(source_tag)
    if withdrawal_req_cnt > 0:
        """We missed a withdrawal request due to odd timing
        Remove the tip txn"""
        await db['custodial-wallet-payments'].delete_one({"transactionId": doc['transactionId']})
        return False, "**Failed** trying to tip when a withdrawal request is in queue"
    return True, "**Success**"


async def get_player_cnt():
    users_collection = db['users']
    top_users = await users_collection.count_documents({})
    return top_users

async def get_xrpl_staked_nfts(addresses):
    try:
        # Fetch staking stats from the 'nft-staking-stats' collection
        staking_stats = db['nft-staking-stats'].find(
            {"primaryAddress": {"$in": addresses}}
        )

        nfts_staked = []

        # Loop through each staking stat and process NFTs
        async for stat in staking_stats:
            for nft_id in stat['nfts'].keys():
                parsed_token = parse_nftoken_id(nft_id)
                nft_token = {
                    **parsed_token,
                    'URI': '',
                    "nft_serial": parsed_token["Sequence"],
                    "NFTokenTaxon": parsed_token["Taxon"],
                }
                nfts_staked.append(nft_token)

        return nfts_staked

    except Exception as e:
        print(f"Error fetching staked NFTs: {e}")
        return []

asyncio.run(remove_user_nft_addr('', '230', False, False, ))