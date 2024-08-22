import asyncio
import logging
import time
import traceback

import nextcord
from nextcord import Role
from xrpl.core.addresscodec import is_valid_classic_address

from rootTest import getOwnedRootNFTs
from utils.refresh_fn import get_type, filter_nfts
import config
from config import TIERS, RANKS
import config_extra
import xrpl_functions
import db_query
from datetime import date


async def check_and_reset_store():
    today = date.today()
    current_day = today.day
    if current_day != config.day:
        config.day = current_day
        config.store_24_hr_buyers = []


async def update_nft_holdings(client: nextcord.Client):
    while True:
        await asyncio.sleep(10)
        # await check_and_reset_store()
        next_runtime = time.time() - 3600
        all_users = await db_query.get_all_users_cursor()
        guilds = client.guilds
        main_servers = [i for i in guilds if i.id == config.MAIN_GUILD[0]]
        main_guild = main_servers[0] if len(main_servers) > 0 else None
        z_role, t_role = None, None
        try:
            z_role = nextcord.utils.get(main_guild.roles, name="Zerpmon Holder")
            t_role = nextcord.utils.get(main_guild.roles, name="Trainer")
        except:
            logging.error("Failed to grab z_role")
        async for old_user in all_users:
            ti = time.time()
            user_obj = old_user

            try:
                if 'username' in user_obj:
                    print(user_obj['username'])
                if 'zerpmons' not in user_obj:
                    continue
                if 'address' not in user_obj or len(user_obj['address']) < 5 or \
                        user_obj['address'] in ['rHvEgvSS4sQR2DSRioKs8rcNXjHwxa6oSe',
                                                'r9cKrPx9uNZJBUPFZpC6Qf7WHmMSfPsFHM',
                                                'r9AHwn5mL6GpchBEie1K1z8S8pqejsyU2k']:
                    continue
                xrpl_addresses, root_addresses = [], []
                linked_addresses = [*user_obj['linked_addresses'], user_obj['address']] if \
                    'linked_addresses' in user_obj else [user_obj['address']]
                good_status_xrpl, good_status_trn, nfts = True, True, []
                for addr in linked_addresses:
                    if is_valid_classic_address(addr):
                        xrpl_addresses.append(addr)
                    else:
                        root_addresses.append(addr)

                for addr in xrpl_addresses:
                    success, found_nfts = await xrpl_functions.get_nfts(addr)
                    if not success:
                        good_status_xrpl = False
                        break
                    nfts.extend(found_nfts)
                if not good_status_xrpl:
                    continue

                success, found_root_nfts = await getOwnedRootNFTs(root_addresses)
                if not success:
                    good_status_trn = False

                # good_status_xahau, nfts_xahau = await xrpl_functions.get_nfts_xahau(user_obj['address'])
                # if not good_status:
                #     continue
                serials = []
                t_serial = []
                e_serial = []
                remove_serials = {
                    'zerpmons': [],
                    'trainer_cards': [],
                    'equipments': []
                }
                # Filter fn
                await filter_nfts(user_obj, nfts, serials, t_serial, e_serial)
                if not good_status_trn:
                    for sr in user_obj['zerpmons']:
                        if str(sr).startswith('trn-'):
                            serials.append(sr)
                    for sr in user_obj['trainer_cards']:
                        if str(sr).startswith('trn-'):
                            serials.append(sr)
                    for sr in user_obj['equipments']:
                        if str(sr).startswith('trn-'):
                            serials.append(sr)
                else:
                    await filter_nfts(user_obj, found_root_nfts, serials, t_serial, e_serial, chain='trn')
                # if not good_status_xahau:
                #     for sr in user_obj['zerpmons']:
                #         if str(sr).startswith('xahau-'):
                #             serials.append(sr)
                #     for sr in user_obj['trainer_cards']:
                #         if str(sr).startswith('xahau-'):
                #             serials.append(sr)
                #     for sr in user_obj['equipments']:
                #         if str(sr).startswith('xahau-'):
                #             serials.append(sr)
                # else:
                #     await filter_nfts(user_obj, nfts_xahau, serials, t_serial, e_serial, xahau=True)
                for serial in list(old_user['zerpmons'].keys()):
                    if serial not in serials:
                        loaned = old_user['zerpmons'][serial].get('loaned', False)
                        if loaned:
                            serials.append(serial)
                        else:
                            # if False:
                            # await db_query.remove_user_nft(user_obj['discord_id'], serial, False)
                            remove_serials['zerpmons'].append(serial)
                for serial in list(user_obj['trainer_cards'].keys()):
                    if serial not in t_serial:
                        loaned = user_obj['trainer_cards'][serial].get('loaned', False)
                        if loaned:
                            t_serial.append(serial)
                        else:
                            remove_serials['trainer_cards'].append(serial)
                            # await db_query.remove_user_nft(user_obj['discord_id'], serial, True)
                for serial in list(user_obj['equipments'].keys()):
                    if serial not in e_serial:
                        loaned = user_obj['equipments'][serial].get('loaned', False)
                        if loaned:
                            e_serial.append(serial)
                        else:
                            remove_serials['equipments'].append(serial)
                            # await db_query.remove_user_nft(user_obj['discord_id'], serial, equipment=True)

                if user_obj.get('discord_id'):
                    if main_guild:
                        if 'guild_id' not in user_obj:
                            user_obj['guild_id'] = main_guild.id
                        try:
                            # await asyncio.sleep(1)
                            user = main_guild.get_member(int(user_obj['discord_id']))
                            if user is None:
                                user = await main_guild.fetch_member(int(user_obj['discord_id']))
                            # print(guild, user)
                            if user is not None:
                                rank_role_1v1 = user_obj.get('rank1', {}).get('tier', 'Unranked')
                                rank_role_3v3 = user_obj.get('rank', {}).get('tier', 'Unranked')
                                rank_role_5v5 = user_obj.get('rank5', {}).get('tier', 'Unranked')
                                rank_role_current = TIERS[max([
                                    TIERS.index(rank_role_1v1),
                                    TIERS.index(rank_role_3v3),
                                    TIERS.index(rank_role_5v5)])]
                                roles_to_add: [Role] = []
                                roles_to_remove: [Role] = []
                                has_rank_role, has_z_role, has_t_role = False, False, False
                                has_1v1_role, has_3v3_role, has_5v5_role = False, False, False
                                for role in user.roles:
                                    match role.name:
                                        case "Novice Trainer" | "Apprentice Battler" | "Elite Explorer" | "Master Tamer" | "Grand Warlord" | "Legendary Trainer" | 'Prestige Trainer':
                                            # Handle the matched roles here
                                            print(f"Matched role: {role.name}")
                                            if role.name != rank_role_current:
                                                roles_to_remove.append(role)
                                            else:
                                                has_rank_role = True
                                        case "Novice Trainer (1v1)" | "Apprentice Battler (1v1)" | "Elite Explorer (1v1)" | "Master Tamer (1v1)" | "Grand Warlord (1v1)" | "Legendary Trainer (1v1)" | 'Prestige Trainer (1v1)':
                                            # Handle the matched roles here
                                            print(f"Matched role: {role.name}")
                                            if role.name != rank_role_1v1 + ' (1v1)':
                                                roles_to_remove.append(role)
                                            else:
                                                has_1v1_role = True
                                        case "Novice Trainer (3v3)" | "Apprentice Battler (3v3)" | "Elite Explorer (3v3)" | "Master Tamer (3v3)" | "Grand Warlord (3v3)" | "Legendary Trainer (3v3)" | 'Prestige Trainer (3v3)':
                                            # Handle the matched roles here
                                            print(f"Matched role: {role.name}")
                                            if role.name != rank_role_3v3 + ' (3v3)':
                                                roles_to_remove.append(role)
                                            else:
                                                has_3v3_role = True
                                        case "Novice Trainer (5v5)" | "Apprentice Battler (5v5)" | "Elite Explorer (5v5)" | "Master Tamer (5v5)" | "Grand Warlord (5v5)" | "Legendary Trainer (5v5)" | 'Prestige Trainer (5v5)':
                                            # Handle the matched roles here
                                            print(f"Matched role: {role.name}")
                                            if role.name != rank_role_5v5 + ' (5v5)':
                                                roles_to_remove.append(role)
                                            else:
                                                has_5v5_role = True
                                        case "Zerpmon Holder":
                                            has_z_role = True
                                        case "Trainer":
                                            has_t_role = True
                                if len(user_obj['zerpmons']) == 0 and has_z_role:
                                    if z_role is not None:
                                        roles_to_remove.append(z_role)
                                elif not has_z_role:
                                    if z_role is not None:
                                        roles_to_add.append(z_role)
                                if len(user_obj['trainer_cards']) == 0 and has_t_role:
                                    if t_role is not None:
                                        roles_to_remove.append(t_role)
                                elif not has_t_role:
                                    if t_role is not None:
                                        roles_to_add.append(t_role)
                                if not has_rank_role:
                                    role = nextcord.utils.get(main_guild.roles, name=rank_role_current)
                                    if role is not None:
                                        roles_to_add.append(role)
                                if not has_1v1_role:
                                    if RANKS[rank_role_1v1]['roles']['1v1']:
                                        roles_to_add.append(RANKS[rank_role_1v1]['roles']['1v1'])
                                if not has_3v3_role:
                                    if RANKS[rank_role_3v3]['roles']['3v3']:
                                        roles_to_add.append(RANKS[rank_role_3v3]['roles']['3v3'])
                                if not has_5v5_role:
                                    if RANKS[rank_role_5v5]['roles']['5v5']:
                                        roles_to_add.append(RANKS[rank_role_5v5]['roles']['5v5'])
                                if len(roles_to_add) > 0:
                                    try:
                                        await user.add_roles(*roles_to_add)
                                    except:
                                        print("USER already has the required roles", [i.name for i in roles_to_add])
                                if len(roles_to_remove) > 0:
                                    try:
                                        await user.remove_roles(*roles_to_remove)
                                    except:
                                        print("Failed to remove roles", [i.name for i in roles_to_remove])
                        except Exception as e:
                            print(f"USER already has the required role {e}")
                        await asyncio.sleep(2)

                await db_query.update_user_decks(user_obj, user_obj['discord_id'], serials, t_serial,
                                                 e_serial, remove_serials)
                print('timeTaken:', time.time() - ti)
            except Exception as e:
                logging.error(f"ERROR while updating NFTs: {traceback.format_exc()}")

            await asyncio.sleep(2)
        try:
            burnt = 1589000 - (await xrpl_functions.get_zrp_balance(address=config.ISSUER['ZRP'], issuer=True))
            await db_query.set_burnt(burnt)
        except:
            pass
        config_extra.deck_item_cache = deck_item_cache = {
            'temp': {},
            'main': {}
        }
        time_to_sleep = int(next_runtime - time.time())
        logging.error(f"Sleep for: {time_to_sleep}")
        await asyncio.sleep(max(10, time_to_sleep))
