import asyncio
import logging
import traceback

import nextcord

import config
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
        await check_and_reset_store()
        all_users = db_query.get_all_users()
        guilds = client.guilds

        for old_user in all_users:
            user_obj = old_user
            try:
                if 'address' not in user_obj or len(user_obj['address']) < 5 or user_obj['address'] == 'rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME':
                    continue
                good_status, nfts = await xrpl_functions.get_nfts(user_obj['address'])
                if not good_status:
                    continue
                serials = []
                t_serial = []
                e_serial = []

                for nft in nfts:

                    if nft["Issuer"] in [config.ISSUER["Trainer"], config.ISSUER["TrainerV2"]]:
                        serial = str(nft["nft_serial"])
                        if serial in list(old_user['trainer_cards'].keys()):
                            t_serial.append(serial)
                            continue
                        print(serial, list(old_user['trainer_cards'].keys()))
                        metadata = xrpl_functions.get_nft_metadata(nft['URI'])
                        if metadata is None:
                            continue

                        if "Zerpmon" in metadata['description']:
                            t_serial.append(serial)
                            # Add to MongoDB here
                            new_z = {"name": metadata['name'],
                                     "image": metadata['image'],
                                     "attributes": metadata['attributes'],
                                     "token_id": nft["NFTokenID"],
                                     }
                            db_query.add_user_nft(user_obj['discord_id'], serial, new_z, True)
                        await asyncio.sleep(2)
                    if nft["Issuer"] == config.ISSUER["Zerpmon"]:
                        serial = str(nft["nft_serial"])
                        if serial in list(old_user['zerpmons'].keys()):
                            serials.append(serial)
                            continue
                        metadata = xrpl_functions.get_nft_metadata(nft['URI'])

                        if "Zerpmon " in metadata['description']:
                            serials.append(serial)
                            try:
                                active_t = user_obj["zerpmons"][serial]['active_t']
                            except:
                                active_t = 0
                            # Add to MongoDB here
                            new_z = {"name": metadata['name'],
                                     "image": metadata['image'],
                                     "attributes": metadata['attributes'],
                                     "token_id": nft["NFTokenID"],
                                     'active_t': active_t
                                     }
                            db_query.add_user_nft(user_obj['discord_id'], serial, new_z, False)
                        await asyncio.sleep(2)
                    if nft["Issuer"] == config.ISSUER["Equipment"]:
                        serial = str(nft["nft_serial"])
                        if serial in list(old_user['equipments'].keys()):
                            e_serial.append(serial)
                            continue
                        print(serial, list(old_user['equipments'].keys()))
                        metadata = xrpl_functions.get_nft_metadata(nft['URI'])

                        if "Zerpmon Equipment" in metadata['description']:
                            e_serial.append(serial)
                            # Add to MongoDB here
                            new_z = {"name": metadata['name'],
                                     "image": metadata['image'],
                                     "attributes": metadata['attributes'],
                                     "token_id": nft["NFTokenID"],
                                     }
                            db_query.add_user_nft(user_obj['discord_id'], serial, new_z, equipment=True)
                        await asyncio.sleep(2)
                for serial in list(old_user['zerpmons'].keys()):
                    if serial not in serials:
                        loaned = old_user['zerpmons'][serial].get('loaned', False)
                        if loaned:
                            serials.append(serial)
                        else:
                            db_query.remove_user_nft(user_obj['discord_id'], serial, False)
                for serial in list(old_user['trainer_cards'].keys()):
                    if serial not in t_serial:
                        db_query.remove_user_nft(user_obj['discord_id'], serial, True)
                for serial in list(old_user['equipments'].keys()):
                    if serial not in e_serial:
                        db_query.remove_user_nft(user_obj['discord_id'], serial, equipment=True)

                if len(user_obj['zerpmons']) > 0 or len(user_obj['trainer_cards']) > 0:
                    for guild in guilds:
                        if 'guild_id' not in user_obj or ('guild_id' in user_obj and user_obj['guild_id'] == guild.id):
                            try:
                                # await asyncio.sleep(1)
                                user = await guild.fetch_member(int(user_obj['discord_id']))
                                print(guild, user)
                                if user is not None:
                                    user_obj['guild_id'] = guild.id
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

                db_query.update_user_decks(user_obj['discord_id'], serials, t_serial)
            except Exception as e:
                logging.error(f"ERROR while updating NFTs: {traceback.format_exc()}")

            await asyncio.sleep(2)
        await asyncio.sleep(900)
