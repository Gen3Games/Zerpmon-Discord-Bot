import json
import time

from pymongo import MongoClient, ReturnDocument, DESCENDING
import config

client = MongoClient(config.MONGO_URL)
db = client['Zerpmon']

# Instantiate Static collections

move_collection = db['MoveList']
level_collection = db['levels']


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
        print(f"Updated user with username {user['username']}")


def remove_user_nft(discord_id, serial, trainer=False):
    users_collection = db['users']
    # Upsert user
    # print(user)

    update_query = {"$unset": {f"zerpmons.{serial}": ""}} if not trainer else \
        {"$unset": {f"trainer_cards.{serial}": ""}}
    result = users_collection.update_one(
        {'discord_id': discord_id},
        update_query
    )


def add_user_nft(discord_id, serial, zerpmon, trainer=False):
    users_collection = db['users']
    # Upsert user
    # print(user)

    doc_str = json.dumps(zerpmon)
    zerpmon = json.loads(doc_str)
    # print(zerpmon)
    update_query = {"$set": {f"zerpmons.{serial}": zerpmon}} if not trainer else \
        {"$set": {f"trainer_cards.{serial}": zerpmon}}
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


def get_zerpmon(name):
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


def get_rand_zerpmon():
    zerpmon_collection = db['MoveSets']
    random_doc = list(zerpmon_collection.aggregate([{'$sample': {'size': 1}}, {'$limit': 1}]))
    # print(random_doc[0])
    return random_doc[0]


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
        return list(top_users[:10])


def add_revive_potion(address, inc_by):
    users_collection = db['users']

    r = users_collection.find_one_and_update({'address': str(address)},
                                             {'$inc': {'revive_potion': inc_by}},
                                             upsert=True,
                                             return_document=ReturnDocument.AFTER)
    # print(r)
    return True


def add_mission_potion(address, inc_by):
    users_collection = db['users']

    r = users_collection.find_one_and_update({'address': str(address)},
                                             {'$inc': {'mission_potion': inc_by}},
                                             upsert=True,
                                             return_document=ReturnDocument.AFTER)
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


def update_trainer_deck(trainer_serial, user_id, deck_no):
    users_collection = db['users']
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


def update_mission_deck(zerpmon_id, place, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {} if "mission_deck" not in doc or doc["mission_deck"] == {} else doc["mission_deck"]
    if arr != {}:
        for k, v in arr.copy().items():
            if v == zerpmon_id:
                del arr[k]

    arr[str(place - 1)] = zerpmon_id
    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'mission_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


def update_battle_deck(zerpmon_id, deck_no, place, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    # add the element to the array
    arr = {'0': {}, '1': {}, '2': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else doc["battle_deck"]
    if arr[deck_no] != {}:
        for k, v in arr[deck_no].copy().items():
            if v == zerpmon_id:
                del arr[deck_no][k]

    arr[deck_no][str(place - 1)] = zerpmon_id
    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'battle_deck': arr}})

    if r.acknowledged:
        return True
    else:
        return False


def set_default_deck(deck_no, user_id):
    users_collection = db['users']

    doc = users_collection.find_one({'discord_id': str(user_id)})

    arr = {'0': {}, '1': {}, '2': {}} if "battle_deck" not in doc or doc["battle_deck"] == {} else doc["battle_deck"]
    arr[deck_no], arr['0'] = arr['0'], arr[deck_no]

    # save the updated document
    r = users_collection.update_one({'discord_id': str(user_id)}, {"$set": {'battle_deck': arr}})

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


def add_xrp(user_id, amount):
    users_collection = db['users']

    r = users_collection.find_one_and_update({'discord_id': str(user_id)},
                                             {'$inc': {'xrp_earned': amount}},
                                             upsert=True,
                                             return_document=ReturnDocument.AFTER)
    # print(r)


def add_xp(zerpmon_name, user_address):
    zerpmon_collection = db['MoveSets']

    old = zerpmon_collection.find_one({'name': zerpmon_name})
    if old:
        level = old.get('level', 0)
        xp = old.get('xp', 0)
        next_lvl = level_collection.find_one({'level': level + 1}) if level < 30 else None

        if next_lvl and xp + 10 >= next_lvl['xp_required']:
            zerpmon_collection.update_one({'name': zerpmon_name}, {'$set': {'level': next_lvl['level'], 'xp': 0}})
            add_revive_potion(user_address, next_lvl['revive_potion_reward'])
            add_mission_potion(user_address, next_lvl['mission_potion_reward'])
        else:
            zerpmon_collection.update_one({'name': zerpmon_name}, {'$inc': {'xp': 10}})
    else:
        # Zerpmon not found, handle the case accordingly
        # For example, you can raise an exception or return False
        return False

    # Rest of the code for successful operation
    return True


def get_lvl_xp(zerpmon_name, in_mission=False) -> tuple:
    zerpmon_collection = db['MoveSets']

    old = zerpmon_collection.find_one({'name': zerpmon_name})
    level = old['level'] + 1 if 'level' in old else 1
    if in_mission and (level - 1) >= 10 and (level - 1) % 10 == 0 and old['xp'] == 0:
        update_moves(old)
    if level > 30:
        level = 30
    last_lvl = level_collection.find_one({'level': (level - 1) if level > 1 else 1})
    next_lvl = level_collection.find_one({'level': level})
    if 'level' in old and 'xp' in old:

        return old['level'], old['xp'], next_lvl['xp_required'], last_lvl['revive_potion_reward'], \
               last_lvl['mission_potion_reward']
    else:
        return 0, 0, next_lvl['xp_required'], last_lvl['revive_potion_reward'], \
               last_lvl['mission_potion_reward']


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
    elif rank['points'] <= user_rank_d['l']:
        next_rank = [r for r, v in config.RANKS.items() if v['h'] == user_rank_d['l']][0]
        rank['tier'] = next_rank
    if not decay:
        rank['last_battle_t'] = time.time()
    users_collection.update_one({'discord_id': str(user_id)},
                                {'$set': {'rank': rank}}
                                )
    return user_rank_d['win'] if win else user_rank_d['loss'], rank, next_rank
    # print(r)


# MOVES UPDATE QUERY

def update_moves(document):
    if 'level' in document and document['level'] / 10 >= 1:
        miss_percent = float([i for i in document['moves'] if i['color'] == 'miss'][0]['percent'])
        percent_change = 3.33 if 3.33 < miss_percent else miss_percent
        count = len([i for i in document['moves'] if i['name'] != ""]) - 1
        print(document)
        for i, move in enumerate(document['moves']):
            if move['color'] == 'miss':
                move['percent'] = str(round(float(move['percent']) - percent_change, 2))
                document['moves'][i] = move
            elif move['name'] != "" and float(move['percent']) > 0:
                move['percent'] = str(round(float(move['percent']) + (percent_change / count), 2))
                document['moves'][i] = move
        del document['_id']
        save_new_zerpmon(document)

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
