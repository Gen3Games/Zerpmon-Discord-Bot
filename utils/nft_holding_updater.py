import asyncio
import logging
import time
import traceback

import nextcord
from utils.refresh_fn import get_type, filter_nfts
import config
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

        async for old_user in all_users:
            ti = time.time()
            user_obj = old_user

            try:
                if 'username' not in user_obj:
                    continue
                print(user_obj['username'])
                if 'address' not in user_obj or len(user_obj['address']) < 5 or \
                        user_obj['address'] in ['rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME', 'r9cKrPx9uNZJBUPFZpC6Qf7WHmMSfPsFHM', 'r9AHwn5mL6GpchBEie1K1z8S8pqejsyU2k']:
                    continue
                good_status, nfts = await xrpl_functions.get_nfts(user_obj['address'])
                if user_obj.get('address_config'):
                    if user_obj['address_config'].get('xrpl'):
                        good_status2, nfts2 = await xrpl_functions.get_nfts(user_obj['address_config'].get('xrpl'))
                        if not good_status2:
                            continue
                        nfts.extend(nfts2)
                good_status_xahau, nfts_xahau = await xrpl_functions.get_nfts_xahau(user_obj['address'])
                if not good_status:
                    continue
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
                if not good_status_xahau:
                    for sr in user_obj['zerpmons']:
                        if str(sr).startswith('xahau-'):
                            serials.append(sr)
                    for sr in user_obj['trainer_cards']:
                        if str(sr).startswith('xahau-'):
                            serials.append(sr)
                    for sr in user_obj['equipments']:
                        if str(sr).startswith('xahau-'):
                            serials.append(sr)
                else:
                    await filter_nfts(user_obj, nfts_xahau, serials, t_serial, e_serial, xahau=True)
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

                if len(user_obj['zerpmons']) > 0 or len(user_obj['trainer_cards']) > 0:
                    for guild in guilds:
                        if 'guild_id' not in user_obj or ('guild_id' in user_obj and user_obj['guild_id'] == guild.id):
                            try:
                                # await asyncio.sleep(1)
                                user = await guild.fetch_member(int(user_obj['discord_id']))
                                print(guild, user)
                                if user is not None:
                                    user_obj['guild_id'] = guild.id
                                    if guild.id != config.MAIN_GUILD[0]:
                                        continue
                                    if len(user_obj['zerpmons']) > 0:
                                        try:
                                            role = nextcord.utils.get(guild.roles, name="Zerpmon Holder")
                                            if role is None:
                                                continue
                                            await user.add_roles(role)
                                        except Exception as e:
                                            print(f"USER already has the required role {traceback.format_exc()}")
                                    if len(user_obj['trainer_cards']) > 0:
                                        try:
                                            role = nextcord.utils.get(guild.roles, name="Trainer")
                                            if role is None:
                                                continue
                                            await user.add_roles(role)
                                        except:
                                            print("USER already has the required role")
                            except Exception as e:
                                print(f"USER already has the required role {e}")
                            await asyncio.sleep(2)

                await db_query.update_user_decks(user_obj, user_obj['discord_id'], serials, t_serial,
                                                 e_serial, remove_serials)
                print('timeTaken:', time.time()-ti)
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
