import datetime
import json
import logging
import random
import time

import pymongo
import pytz
from pymongo import MongoClient, ReturnDocument, DESCENDING, UpdateOne
import config

client = MongoClient(config.MONGO_URL)
db = client['Zerpmon']

# Instantiate Static collections

move_collection = db['MoveList']
level_collection = db['levels']
equipment_col = db['Equipment']


def get_next_ts(days=1):
    # Get the current time in UTC
    current_time = datetime.datetime.now(pytz.utc)

    # Calculate the time difference until the next UTC 00:00
    next_day = current_time + datetime.timedelta(days=days)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    return target_time.timestamp()


def save_user(user):
    users_collection = db['users']
    # Upsert user
    # print(user)

    doc_str = json.dumps(user)
    user = json.loads(doc_str)
    print(user)
    result = users_collection.update_one(
        {'discord_id': user['discord_id']},
        {'$set': user},
        upsert=True
    )

    if result.upserted_id:
        print(f"Created new user with id {result.upserted_id}")
    else:
        print(f"Updated user")


def update_user_decks(discord_id, serials, t_serial):
    user_obj = get_owned(discord_id)

    mission_trainer = user_obj["mission_trainer"] if 'mission_trainer' in user_obj else ""
    mission_deck = user_obj["mission_deck"] if 'mission_deck' in user_obj else {}
    battle_deck = user_obj["battle_deck"] if 'battle_deck' in user_obj else {}
    gym_deck = user_obj["gym_deck"] if 'gym_deck' in user_obj else {}

    new_mission_deck = {}
    for k, v in mission_deck.items():
        if v in serials:
            new_mission_deck[k] = v
    if mission_trainer not in t_serial:
        mission_trainer = ""
    new_battle_deck = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}}
    for k, v in battle_deck.items():
        for serial in v:
            if serial == "trainer":
                if v[serial] in t_serial:
                    new_battle_deck[k][serial] = v[serial]
            elif v[serial] in serials:
                new_battle_deck[k][serial] = v[serial]

    new_gym_deck = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}}
    for k, v in gym_deck.items():
        for serial in v:
            if serial == "trainer":
                if v[serial] in t_serial:
                    new_gym_deck[k][serial] = v[serial]
            elif v[serial] in serials:
                new_gym_deck[k][serial] = v[serial]

    logging.error(f'Serials {serials} \nnew deck: {new_battle_deck}')
    save_user({'mission_trainer': mission_trainer, 'mission_deck': new_mission_deck,
               'battle_deck': new_battle_deck, 'gym_deck': new_gym_deck,
               'discord_id': user_obj["discord_id"]})


def remove_user_nft(discord_id, serial, trainer=False, equipment=False):
    users_collection = db['users']
    # Upsert user
    # print(user)

    update_query = {"$unset": {f"equipments.{serial}": ""}} if equipment else (
        {"$unset": {f"zerpmons.{serial}": ""}} if not trainer else {"$unset": {f"trainer_cards.{serial}": ""}})
    result = users_collection.update_one(
        {'discord_id': discord_id},
        update_query
    )


def add_user_nft(discord_id, serial, zerpmon, trainer=False, equipment=False):
    users_collection = db['users']
    # Upsert user
    # print(user)

    doc_str = json.dumps(zerpmon)
    zerpmon = json.loads(doc_str)
    # print(zerpmon)
    update_query = {"$set": {f"equipments.{serial}": zerpmon}} if equipment else (
        {"$set": {f"zerpmons.{serial}": zerpmon}} if not trainer else
        {"$set": {f"trainer_cards.{serial}": zerpmon}})
    result = users_collection.update_one(
        {'discord_id': discord_id},
        update_query
    )


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


def get_all_users():
    users_collection = db['users']

    result = users_collection.find()
    return [i for i in result]


def get_owned(user_id):
    users_collection = db['users']
    # Upsert user
    # print(user_id)

    user_id = str(user_id)
    result = users_collection.find_one({"discord_id": user_id})

    # print(f"Found user {result}")

    return result


def check_wallet_exist(address):
    users_collection = db['users']
    # Upsert user
    # print(address)

    user_id = str(address)
    result = users_collection.find_one({"address": user_id})

    # print(f"Found user {result}")

    return result is not None


def get_user(address):
    users_collection = db['users']
    # Upsert user
    # print(address)

    user_id = str(address)
    result = users_collection.find_one({"address": user_id})

    # print(f"Found user {result}")

    return result


def get_move(name):
    # print(name)

    result = move_collection.find_one({"move_name": name})

    # print(f"Found move {result}")

    return result


def get_zerpmon(name, mission=False):
    if mission:
        zerpmon_collection = db['MoveSets2']
    else:
        zerpmon_collection = db['MoveSets']
    # print(name)

    result = zerpmon_collection.find_one({"name": name})
    if result is None:
        result = zerpmon_collection.find_one({"nft_id": str(name).upper()})

    # print(f"Found Zerpmon {result}")

    return result


def save_zerpmon_winrate(winner_name, loser_name):
    zerpmon_collection = db['MoveSets']
    # print(winner_name, loser_name)

    winner = zerpmon_collection.find_one({"name": winner_name})

    total = 0 if 'total' not in winner else winner['total']
    new_wr = 100 if 'winrate' not in winner else ((winner['winrate'] * total) + 100) / (total + 1)
    u1 = zerpmon_collection.find_one_and_update({"name": winner_name},
                                                {'$set': {'total': total + 1,
                                                          'winrate': new_wr}})

    loser = zerpmon_collection.find_one({"name": loser_name})
    total = 0 if 'total' not in loser else loser['total']
    new_wr = 0 if 'winrate' not in loser else (loser['winrate'] * total) / (total + 1)
    u2 = zerpmon_collection.find_one_and_update({"name": loser_name},
                                                {'$set': {'total': total + 1,
                                                          'winrate': new_wr}})

    return True


def get_rand_zerpmon(level):
    zerpmon_collection = db['MoveSets2']
    random_doc = list(zerpmon_collection.aggregate([{'$sample': {'size': 1}}, {'$limit': 1}]))
    zerp = random_doc[0]
    zerp['level'] = level
    for i in range(level // 10):
        zerp = update_moves(zerp, False)
    # print(random_doc[0])
    return zerp


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


def update_level(name, new_lvl):
    zerpmon_collection = db['MoveSets']
    zerpmon_collection.find_one_and_update({'name': name}, {'$set': {'level': new_lvl}})


def update_zerpmon_alive(zerpmon, serial, user_id):
    users_collection = db['users']
    if 'buff_eq' in zerpmon:
        del zerpmon['buff_eq']
    if 'eq_applied' in zerpmon:
        del zerpmon['eq_applied']
    r = users_collection.find_one_and_update({'discord_id': str(user_id)},
                                             {'$set': {f'zerpmons.{serial}': zerpmon}},
                                             return_document=ReturnDocument.AFTER)
    # print(r)


def update_battle_count(user_id, num):
    from utils.checks import get_next_ts
    users_collection = db['users']
    new_ts = get_next_ts()
    r = users_collection.find_one({'discord_id': str(user_id)})
    if 'battle' in r and r['battle']['num'] > 0 and new_ts - r['battle']['reset_t'] > 80000:
        num = -1
    users_collection.update_one({'discord_id': str(user_id)},
                                {'$set': {'battle': {
                                    'num': num + 1,
                                    'reset_t': new_ts
                                }}})
    # print(r)


def update_user_wr(user_id, win):
    users_collection = db['users']

    r = None
    if win == 1:
        r = users_collection.update_one({'discord_id': str(user_id)},
                                        {'$inc': {'win': 1, 'loss': 0, 'total_matches': 1}},
                                        upsert=True)
    elif win == 0:
        r = users_collection.update_one({'discord_id': str(user_id)},
                                        {'$inc': {'loss': 1, 'win': 0, 'total_matches': 1}},
                                        upsert=True)

    if r.acknowledged:
        return True
    else:
        return False


def update_pvp_user_wr(user_id, win):
    users_collection = db['users']

    r = None
    if win == 1:
        r = users_collection.update_one({'discord_id': str(user_id)},
                                        {'$inc': {'pvp_win': 1, 'pvp_loss': 0}},
                                        upsert=True)
    elif win == 0:
        r = users_collection.update_one({'discord_id': str(user_id)},
                                        {'$inc': {'pvp_loss': 1, 'pvp_win': 0}},
                                        upsert=True)

    if r.acknowledged:
        return True
    else:
        return False


def get_top_players(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'win': {'$exists': True}}
    top_users = users_collection.find(query).sort('win', DESCENDING).limit(10)
    top_users = [i for i in top_users]

    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = users_collection.find_one({'discord_id': user_id})
        if curr_user and 'win' not in curr_user:
            curr_user['win'] = 0
            curr_user['loss'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = users_collection.count_documents({'win': {'$gt': curr_user['win']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return top_users


def get_pvp_top_players(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'pvp_win': {'$exists': True}}
    top_users = users_collection.find(query).sort('pvp_win', DESCENDING).limit(10)
    top_users = [i for i in top_users]
    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = users_collection.find_one({'discord_id': user_id})
        if curr_user and 'pvp_win' not in curr_user:
            curr_user['pvp_win'] = 0
            curr_user['pvp_loss'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = users_collection.count_documents({'pvp_win': {'$gt': curr_user['pvp_win']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return [i for i in top_users]


def get_top_purchasers(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'xrp_spent': {'$exists': True}}
    top_users = users_collection.find(query).sort('xrp_spent', DESCENDING).limit(10)
    top_users = [i for i in top_users]
    if user_id not in [i['discord_id'] for i in top_users]:
        curr_user = users_collection.find_one({'discord_id': user_id})
        if curr_user and 'xrp_spent' not in curr_user:
            curr_user['xrp_spent'] = 0
            curr_user['mission_purchase'] = 0
            curr_user['revive_purchase'] = 0
            curr_user['rank'] = "-"

            top_users.append(curr_user)
        elif curr_user:
            curr_user_rank = users_collection.count_documents({'xrp_spent': {'$gt': curr_user['xrp_spent']}})
            curr_user['rank'] = curr_user_rank + 1
            top_users.append(curr_user)

    return [i for i in top_users]


def get_ranked_players(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'rank': {'$exists': True}}
    top_users = users_collection.find(query).sort('rank.points', DESCENDING)
    curr_user = users_collection.find_one({'discord_id': user_id})
    if curr_user:
        curr_user_rank = users_collection.count_documents({'rank.points': {'$gt': curr_user['rank']['points'] if 'rank'
                                                                                                                 in curr_user else 0}})
        curr_user['ranked'] = curr_user_rank + 1
        top_users_count = users_collection.count_documents(query)

        rank_limit = 4  # Number of players above and below to show
        rank_above = max(0, curr_user['ranked'] - rank_limit)
        rank_below = min(top_users_count, curr_user['ranked'] + rank_limit + 1)

        top_users = list(top_users[rank_above:rank_below])
        for i, user in enumerate(top_users):
            top_users[i]['ranked'] = rank_above + 1
            rank_above += 1

        if curr_user['discord_id'] not in [i['discord_id'] for i in top_users]:
            if 'rank' not in curr_user:
                curr_user['rank'] = {'tier': 'Unranked', 'points': 0}
            top_users.append(curr_user)
        return top_users
    else:
        users = list(top_users[:7])
        for i, user in enumerate(users):
            users[i]['ranked'] = i + 1
        return users


def add_revive_potion(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'revive_potion': inc_by}
    if purchased:
        query['xrp_spent'] = amount
        query['revive_purchase'] = inc_by
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)

    return True


def add_mission_potion(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']

    query = {'mission_potion': inc_by}
    if purchased:
        query['xrp_spent'] = amount
        query['mission_purchase'] = inc_by
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)
    # print(r)


def add_gym_refill_potion(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']

    query = {'gym.refill_potion': inc_by}
    if purchased:
        query['zrp_spent'] = amount
        query['gym.refill_purchase'] = inc_by
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)
    # print(r)


def reset_respawn_time(user_id):
    users_collection = db['users']
    old = users_collection.find_one({'discord_id': str(user_id)})

    for k, z in old['zerpmons'].items():
        old['zerpmons'][k]['active_t'] = 0

    old['battle'] = {'num': 0, 'reset_t': -1}

    r = users_collection.find_one_and_update({'discord_id': str(user_id)},
                                             {'$set': old},
                                             return_document=ReturnDocument.AFTER)


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


def update_trainer_deck(trainer_serial, user_id, deck_no, gym=False):
    users_collection = db['users']
    if gym:
        update_query = {
            f'gym_deck.{deck_no}.trainer': trainer_serial
        }
    else:
        update_query = {
            f'battle_deck.{deck_no}.trainer': trainer_serial
        }

    r = users_collection.update_one({'discord_id': str(user_id)},
                                    {'$set': update_query})

    if r.acknowledged:
        return True
    else:
        return False


def update_mission_trainer(trainer_serial, user_id):
    users_collection = db['users']
    update_query = {
        f'mission_trainer': trainer_serial
    }

    r = users_collection.update_one({'discord_id': str(user_id)},
                                    {'$set': update_query})

    if r.acknowledged:
        return True
    else:
        return False


def update_mission_deck(new_deck, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {} if "mission_deck" not in doc or doc["mission_deck"] == {} else doc["mission_deck"]
    # if arr != {}:
    #     for k, v in arr.copy().items():
    #         if v == zerpmon_id:
    #             del arr[k]
    #
    # arr[str(place - 1)] = zerpmon_id
    arr = new_deck
    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'mission_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


def clear_mission_deck(user_id):
    users_collection = db['users']
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'mission_deck': {}}})

    if r.acknowledged:
        return True
    else:
        return False


def update_battle_deck(deck_no, new_deck, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else \
        doc["battle_deck"]
    if deck_no not in arr:
        arr[deck_no] = {}
    # if arr[deck_no] != {}:
    #     for k, v in arr[deck_no].copy().items():
    #         if v == zerpmon_id:
    #             del arr[deck_no][k]
    #
    # arr[deck_no][str(place - 1)] = zerpmon_id
    arr[deck_no] = new_deck
    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'battle_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


def clear_battle_deck(deck_no, user_id, gym=False):
    users_collection = db['users']
    if gym:
        r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'gym_deck.{deck_no}': {}}})
    else:
        r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'battle_deck.{deck_no}': {}}})

    if r.acknowledged:
        return True
    else:
        return False


def update_gym_deck(deck_no, new_deck, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "gym_deck" not in doc or doc["gym_deck"] == {} else doc[
        "gym_deck"]
    if deck_no not in arr:
        arr[deck_no] = {}
    # if arr[deck_no] != {}:
    #     for k, v in arr[deck_no].copy().items():
    #         if v == zerpmon_id:
    #             del arr[deck_no][k]
    #
    # arr[deck_no][str(place - 1)] = zerpmon_id
    arr[deck_no] = new_deck
    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'gym_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


def clear_gym_deck(deck_no, user_id):
    users_collection = db['users']
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {f'gym_deck.{deck_no}': {}}})
    if r.acknowledged:
        return True
    else:
        return False


def set_default_deck(deck_no, user_id, gym=False):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})
    if gym:
        arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "gym_deck" not in doc or doc["gym_deck"] == {} else doc[
            "gym_deck"]
        arr[deck_no], arr['0'] = arr['0'], arr[deck_no]
        eq_deck = doc['equipment_decks']['gym_deck']
        eq_deck[deck_no], eq_deck['0'] = eq_deck['0'], eq_deck[deck_no]

        # save the updated document
        r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'gym_deck': arr, 'equipment_decks.gym_deck': eq_deck }})
    else:
        arr = {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else \
            doc["battle_deck"]
        arr[deck_no], arr['0'] = arr['0'], arr[deck_no]
        eq_deck = doc['equipment_decks']['battle_deck']
        eq_deck[deck_no], eq_deck['0'] = eq_deck['0'], eq_deck[deck_no]
        # save the updated document
        r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'battle_deck': arr, 'equipment_decks.battle_deck': eq_deck}})

    if r.acknowledged:
        return True
    else:
        return False


def reset_deck():
    users_collection = db['users']

    doc = users_collection.find()

    for user in doc:
        r = users_collection.update_one({'discord_id': str(user['discord_id'])}, {"$set": {'battle_deck': {}}})


def revive_zerpmon(user_id):
    users_collection = db['users']
    old = users_collection.find_one({'discord_id': str(user_id)})
    addr = old['address']

    for k, z in old['zerpmons'].items():
        old['zerpmons'][k]['active_t'] = 0

    r = users_collection.update_one({'discord_id': str(user_id)},
                                    {'$set': old}, )
    add_revive_potion(addr, -1)

    if r.acknowledged:
        return True
    else:
        return False


def mission_refill(user_id):
    users_collection = db['users']
    old = users_collection.find_one({'discord_id': str(user_id)})
    addr = old['address']
    old['battle'] = {
        'num': 0,
        'reset_t': -1
    }

    r = users_collection.update_one({'discord_id': str(user_id)},
                                    {'$set': old}, )
    add_mission_potion(addr, -1)

    if r.acknowledged:
        return True
    else:
        return False


def gym_refill(user_id):
    users_collection = db['users']
    old = users_collection.find_one({'discord_id': str(user_id)})
    addr = old['address']
    if 'gym' in old:
        for i in old['gym']['won']:
            if old['gym']['won'][i]['lose_streak'] > 0:
                old['gym']['won'][i]['next_battle_t'] = -1
                old['gym']['won'][i]['lose_streak'] -= 1
        r = users_collection.update_one({'discord_id': str(user_id)},
                                        {'$set': {'gym': old['gym']}}, )
        add_gym_refill_potion(addr, -1)

        if r.acknowledged:
            return True
        else:
            return False
    return False


def add_xrp(user_id, amount):
    users_collection = db['users']

    r = users_collection.find_one_and_update({'discord_id': str(user_id)},
                                             {'$inc': {'xrp_earned': amount}},
                                             upsert=True,
                                             return_document=ReturnDocument.AFTER)
    # print(r)


def add_xp(zerpmon_name, user_address, double_xp=False):
    zerpmon_collection = db['MoveSets']

    old = zerpmon_collection.find_one({'name': zerpmon_name})
    xp_add = 10
    if double_xp:
        xp_add = 20
    if old:
        level = old.get('level', 0)
        xp = old.get('xp', 0)
        next_lvl = level_collection.find_one({'level': level + 1}) if level < 30 else None

        if next_lvl and xp + xp_add >= next_lvl['xp_required']:
            zerpmon_collection.update_one({'name': zerpmon_name}, {
                '$set': {'level': next_lvl['level'], 'xp': (xp + xp_add) - next_lvl['xp_required']}})
            add_revive_potion(user_address, next_lvl['revive_potion_reward'])
            add_mission_potion(user_address, next_lvl['mission_potion_reward'])
        else:
            maxed = old.get('maxed_out', 0)
            if level != 30:
                zerpmon_collection.update_one({'name': zerpmon_name}, {'$inc': {'xp': xp_add}})
            elif level == 30 and maxed == 0:
                zerpmon_collection.update_one({'name': zerpmon_name}, {'$set': {'maxed_out': 1}})
    else:
        # Zerpmon not found, handle the case accordingly
        # For example, you can raise an exception or return False
        return False

    # Rest of the code for successful operation
    return True


def get_lvl_xp(zerpmon_name, in_mission=False, get_candies=False) -> tuple:
    zerpmon_collection = db['MoveSets']

    old = zerpmon_collection.find_one({'name': zerpmon_name})
    level = old['level'] + 1 if 'level' in old else 1
    maxed = old.get('maxed_out', 0)
    if maxed == 0 and in_mission and (level - 1) >= 10 and (level - 1) % 10 == 0 and old['xp'] == 0:
        update_moves(old)
    if level > 30:
        level = 30
    last_lvl = level_collection.find_one({'level': (level - 1) if level > 1 else 1})
    next_lvl = level_collection.find_one({'level': level})
    if 'level' in old and 'xp' in old:

        vals = old['level'], old['xp'], next_lvl['xp_required'] if not get_candies else (
            next_lvl['xp_required'], old.get('white_candy', 0)), \
               last_lvl['revive_potion_reward'] if not get_candies else old.get('gold_candy', 0), \
               last_lvl['mission_potion_reward'] if not get_candies else old.get('licorice', 0)
    else:
        vals = 0, 0, next_lvl['xp_required'] if not get_candies else (
            next_lvl['xp_required'], old.get('white_candy', 0)), \
               last_lvl['revive_potion_reward'] if not get_candies else old.get('gold_candy', 0), \
               last_lvl['mission_potion_reward'] if not get_candies else old.get('licorice', 0)

    return vals


# RANK QUERY

def update_rank(user_id, win, decay=False):
    users_collection = db['users']
    usr = get_owned(user_id)
    next_rank = None
    if 'rank' in usr:
        rank = usr['rank']
    else:
        rank = {
            'tier': 'Unranked',
            'points': 0,
        }
    user_rank_d = config.RANKS[rank['tier']]
    if decay:
        decay_tiers = config.TIERS[-2:]
        rank['points'] -= 50 if rank['tier'] == decay_tiers[0] else 100
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
    users_collection.update_one({'discord_id': str(user_id)},
                                {'$set': {'rank': rank}}
                                )
    return user_rank_d['win'] if win else user_rank_d['loss'], rank, next_rank
    # print(r)


def get_random_doc_with_type(type_value):
    collection = db['MoveSets2']
    query = {'attributes': {'$elemMatch': {'trait_type': 'Type', 'value': type_value}}}
    documents = list(collection.find(query))
    if documents:
        random_documents = random.sample(documents, 5)
        return random_documents
    else:
        return None


def choose_gym_zerp():
    collection_name = 'gym_zerp'
    gym_col = db[collection_name]
    for leader_type in config.GYMS:
        leader_name = f'{leader_type} Gym Leader'
        gym_obj = {'name': leader_name,
                   'zerpmons': None,
                   'image': f'./static/gym/{leader_name}.png',
                   'bg': f'./static/gym/{leader_type}.png'}
        while gym_obj['zerpmons'] is None:
            gym_obj['zerpmons'] = get_random_doc_with_type(leader_type)
        gym_col.update_one({'name': leader_name},
                           {'$set': gym_obj}, upsert=True)


def get_gym_leader(gym_type):
    collection_name = 'gym_zerp'
    gym_col = db[collection_name]
    leader_name = f'{gym_type} Gym Leader'
    res = gym_col.find_one({'name': leader_name})
    return res


def reset_gym(discord_id, gym_obj, gym_type, lost=True, skipped=False):
    users_collection = db['users']
    if gym_obj == {}:
        gym_obj = {
            'won': {
                gym_type: {
                    'stage': 1,
                    'next_battle_t': get_next_ts(1) if lost else 0,
                    'lose_streak': 1
                }
            },
            'active_t': 0,
            'gp': 0
        }
    else:
        l_streak = 1 if gym_type not in gym_obj['won'] else (gym_obj['won'][gym_type]['lose_streak'] + 1)
        reset_limit = 4
        if skipped:
            reset_limit = 3
        gym_obj['won'][gym_type] = {
            'stage': 1 if l_streak == reset_limit else (
                gym_obj['won'][gym_type]['stage'] if gym_type in gym_obj['won'] else 1),
            'next_battle_t': get_next_ts(1) if lost else (
                gym_obj['won'][gym_type]['next_battle_t'] if gym_type in gym_obj['won'] else 0),
            'lose_streak': 0 if l_streak == reset_limit else (l_streak if skipped or lost else l_streak - 1)
        }
    users_collection.update_one(
        {'discord_id': str(discord_id)},
        {'$set': {'gym': gym_obj}}
    )


def add_gp(discord_id, gym_obj, gym_type, stage):
    users_collection = db['users']
    if gym_obj == {}:
        gym_obj = {
            'won': {
                gym_type: {
                    'stage': 2,
                    'next_battle_t': config.gym_main_reset,
                    'lose_streak': 0
                }
            },
            'active_t': 0,
            'gp': 1
        }
    else:
        gym_obj['won'][gym_type] = {
            'stage': stage + 1 if stage < 10 else 1,
            'next_battle_t': config.gym_main_reset,
            'lose_streak': 0
        }
        gym_obj['gp'] += stage
    users_collection.update_one(
        {'discord_id': str(discord_id)},
        {'$set': {'gym': gym_obj}}
    )


def get_gym_leaderboard(user_id):
    users_collection = db['users']
    user_id = str(user_id)
    query = {'gym': {'$exists': True}}
    top_users = users_collection.find(query).sort('gym.gp', DESCENDING)
    curr_user = users_collection.find_one({'discord_id': user_id})
    top_users_count = users_collection.count_documents(query)
    if curr_user:
        curr_user_rank = users_collection.count_documents(
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


def update_user_bg(user_id, gym_type):
    users_collection = db['users']
    user_id = str(user_id)
    bg_value = f'./static/gym/{gym_type}.png'
    users_collection.update_one({'discord_id': user_id},
                                {'$push': {'bg': bg_value}})


def update_user_flair(user_id, flair_name):
    users_collection = db['users']
    user_id = str(user_id)
    users_collection.update_one({'discord_id': user_id},
                                {'$push': {'flair': flair_name}})


def set_user_bg(user_obj, gym_type):
    user_id = user_obj['discord_id']
    bgs = user_obj['bg']
    users_collection = db['users']
    bg_value = f'./static/gym/{gym_type}.png'
    index = bgs.index(bg_value)
    bgs[0], bgs[index] = bgs[index], bgs[0]
    users_collection.update_one({'discord_id': user_id},
                                {'$set': {'bg': bgs}})


def set_user_flair(user_obj, flair):
    user_id = user_obj['discord_id']
    flairs = user_obj['flair']
    users_collection = db['users']
    index = flairs.index(flair)
    flairs[0], flairs[index] = flairs[index], flairs[0]
    users_collection.update_one({'discord_id': user_id},
                                {'$set': {'flair': flairs}})


def double_xp_24hr(user_id):
    users_collection = db['users']

    user_record = users_collection.find_one({'discord_id': str(user_id)})
    if user_record:
        current_time = time.time()
        if user_record.get('double_xp', 0) > current_time:
            new_double_xp = user_record['double_xp'] + 86400
        else:
            new_double_xp = current_time + 86400

        r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'double_xp': new_double_xp}})

        if r.acknowledged:
            return True
        else:
            return False
    else:
        return False


def increase_lvl(user_id, zerpmon_name):
    zerpmon_collection = db['MoveSets']
    users_collection = db['users']
    user = users_collection.find_one({'discord_id': str(user_id)})

    old = zerpmon_collection.find_one({'name': zerpmon_name})
    user_address = user['address']
    if old:
        level = old.get('level', 0)
        xp = old.get('xp', 0)
        next_lvl = level_collection.find_one({'level': level + 1}) if level < 30 else None

        if next_lvl:
            new_doc = zerpmon_collection.find_one_and_update({'name': zerpmon_name},
                                                             {'$set': {'level': next_lvl['level'], 'xp': xp},
                                                              '$inc': {'licorice': 1}},
                                                             return_document=ReturnDocument.AFTER)
            if next_lvl['level'] >= 10 and next_lvl['level'] % 10 == 0:
                update_moves(new_doc)
            add_revive_potion(user_address, next_lvl['revive_potion_reward'])
            add_mission_potion(user_address, next_lvl['mission_potion_reward'])

            add_lvl_candy(user_address, -1)
            return True
    return False


# choose_gym_zerp()
# MOVES UPDATE QUERY


def add_equipment(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'equipment': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)

    return True


def add_white_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'white_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)

    return True


def add_gold_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'gold_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)

    return True


def add_lvl_candy(address, inc_by, purchased=False, amount=0):
    users_collection = db['users']
    query = {'lvl_candy': inc_by}
    if purchased:
        query['zrp_spent'] = amount
    users_collection.update_one({'address': str(address)},
                                {'$inc': query},
                                upsert=True)

    return True


def apply_white_candy(user_id, zerp_name):
    z_collection = db['MoveSets']
    users_collection = db['users']
    user = users_collection.find_one({'discord_id': str(user_id)})
    zerp = z_collection.find_one({'name': zerp_name})
    if zerp.get('white_candy', 0) >= 5:
        return False

    original_zerp = db['MoveSets2'].find_one({'name': zerp_name})
    for i, move in enumerate(zerp['moves']):
        if move['color'].lower() == 'white':
            zerp['moves'][i]['dmg'] = round(zerp['moves'][i]['dmg'] + (original_zerp['moves'][i]['dmg'] * 0.02), 1)
    del zerp['_id']
    white_candy_usage = zerp.get('white_candy', 0)
    zerp['white_candy'] = white_candy_usage + 1
    save_new_zerpmon(zerp)
    add_white_candy(user['address'], -1)
    return True


def apply_gold_candy(user_id, zerp_name):
    z_collection = db['MoveSets']
    users_collection = db['users']
    user = users_collection.find_one({'discord_id': str(user_id)})
    zerp = z_collection.find_one({'name': zerp_name})
    if zerp.get('white_candy', 0) >= 5:
        return False

    original_zerp = db['MoveSets2'].find_one({'name': zerp_name})
    for i, move in enumerate(zerp['moves']):
        if move['color'].lower() == 'gold':
            zerp['moves'][i]['dmg'] = round(zerp['moves'][i]['dmg'] + original_zerp['moves'][i]['dmg'] * 0.02, 1)
    del zerp['_id']
    gold_candy_usage = zerp.get('gold_candy', 0)
    zerp['gold_candy'] = gold_candy_usage + 1
    save_new_zerpmon(zerp)
    add_gold_candy(user['address'], -1)
    return True


def update_moves(document, save_z=True):
    if 'level' in document and document['level'] / 10 >= 1:
        miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
        dec_percent = 3.34 if document['level'] >= 30 else 3.33
        percent_change = dec_percent if dec_percent < miss_percent else miss_percent
        count = len([i for i in document['moves'] if i['name'] != ""]) - 1
        print(document)
        for i, move in enumerate(document['moves']):
            if move['color'] == 'miss':
                move['percent'] = str(round(float(move['percent']) - percent_change, 2))
                document['moves'][i] = move
            elif move['name'] != "" and float(move['percent']) > 0:
                move['percent'] = str(round(float(move['percent']) + (percent_change / count), 2))
                document['moves'][i] = move
        if save_z:
            del document['_id']
            save_new_zerpmon(document)

    return document


# def update_all_zerp_moves():
#     for document in db['MoveSets'].find():
#         if 'level' in document and document['level'] / 10 >= 1:
#             miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
#             percent_change = 3.33 * (document['level'] // 10)
#             percent_change = percent_change if percent_change < miss_percent else miss_percent
#             count = len([i for i in document['moves'] if i['name'] != ""]) - 1
#             print(document)
#             for i, move in enumerate(document['moves']):
#                 if move['color'] == 'miss':
#                     move['percent'] = str(round(float(move['percent']) - percent_change, 2))
#                     document['moves'][i] = move
#                 elif move['name'] != "" and float(move['percent']) > 0:
#                     move['percent'] = str(round(float(move['percent']) + (percent_change / count), 2))
#                     document['moves'][i] = move
#             del document['_id']
#             save_new_zerpmon(document)
#
# update_all_zerp_moves()
# print(get_rand_zerpmon(level=1))
# print(len(get_ranked_players(0)))


def get_zrp_stats():
    stats_col = db['stats_log']
    obj = stats_col.find_one({'name': 'zrp_stats'})
    return obj


def get_gym_reset():
    stats_col = db['stats_log']
    reset_t = stats_col.find_one({'name': 'zrp_stats'}).get('gym_reset_t', 0)
    if reset_t < time.time() - 3600:
        stats_col.update_one({
            'name': 'zrp_stats'
        },
            {'$set': {'gym_reset_t': get_next_ts(3)}}, upsert=True
        )
        return get_next_ts(3)
    else:
        return reset_t


def set_gym_reset():
    stats_col = db['stats_log']
    reset_t = stats_col.find_one({'name': 'zrp_stats'}).get('gym_reset_t', 0)
    if reset_t < time.time() + 60:
        reset_t = get_next_ts(4) if reset_t > time.time() else get_next_ts(3)
        stats_col.update_one({
            'name': 'zrp_stats'
        },
            {'$set': {'gym_reset_t': reset_t}}, upsert=True
        )
        config.gym_main_reset = reset_t


def update_zrp_stats(burn_amount, distributed_amount, left_amount=None, jackpot_amount=0):
    stats_col = db['stats_log']
    query = {'$inc': {'burnt': burn_amount, 'distributed': distributed_amount, 'jackpot_amount': jackpot_amount}}
    if left_amount is not None:
        query['$set'] = {'left_amount': left_amount}
    else:
        query['$inc']['left_amount'] = 0
    print(query)
    stats_col.update_one({
        'name': 'zrp_stats'
    },
        query, upsert=True
    )


"""BATTLE LOGS"""


def update_battle_log(user1_id, user2_id, user1_name, user2_name, user1_team, user2_team, winner, battle_type):
    battle_log = db['battle_logs']
    bulk_operations = []
    if user1_id is not None:
        user1_update = UpdateOne(
            {'discord_id': str(user1_id)},
            {'$push': {'matches': {'ts': int(time.time()), 'won': winner == 1, 'opponent': user2_name,
                                   'battle_type': battle_type,
                                   'data': {'teamA': user1_team, 'teamB': user2_team}}}},
            upsert=True
        )
        bulk_operations.append(user1_update)

    if user2_id is not None:
        user2_update = UpdateOne(
            {'discord_id': str(user2_id)},
            {'$push': {'matches': {'ts': int(time.time()), 'won': winner == 2, 'opponent': user1_name,
                                   'battle_type': battle_type,
                                   'data': {'teamA': user2_team, 'teamB': user1_team}}}},
            upsert=True
        )
        bulk_operations.append(user2_update)

    battle_log.bulk_write(bulk_operations)

    if user1_id is not None:
        battle_log.update_one({'discord_id': str(user1_id)}, {'$push': {'matches': {'$each': [], '$slice': -10}}})

    if user2_id is not None:
        battle_log.update_one({'discord_id': str(user2_id)}, {'$push': {'matches': {'$each': [], '$slice': -10}}})


def get_battle_log(user1_id):
    battle_log = db['battle_logs']
    return battle_log.find_one({'discord_id': str(user1_id)})


"""EQUIPMENT"""


def set_equipment_on(user_id, equipments, deck_type, deck_no):
    users_collection = db['users']
    user_id = str(user_id)
    equipments = {str(i): eq for i, eq in enumerate(equipments)}
    res = users_collection.update_one({'discord_id': user_id},
                                {'$set': {f'equipment_decks.{deck_type}{ "." + deck_no if deck_no is not None else ""}': equipments}},
                                      upsert=True)
    print(res.acknowledged, res.matched_count, res.raw_result)


def get_eq_by_name(name):
    return equipment_col.find_one({'name': name},)


def get_all_eqs():
    return [i for i in equipment_col.find({})]