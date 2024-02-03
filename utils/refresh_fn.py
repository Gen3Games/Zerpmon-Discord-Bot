import asyncio
import logging
import traceback
from nextcord import Interaction, utils
from config import ISSUER, MAIN_GUILD
import db_query
import xrpl_functions


async def refresh_nfts(interaction: Interaction, user_doc, old_address=None):
    guild = interaction.guild
    if old_address is not None:
        if not db_query.update_address(user_doc['address'], old_address):
            return False
    user_obj = user_doc
    try:
        if 'address' not in user_obj or len(user_obj['address']) < 5 or user_obj['address'] == 'rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME':
            return False
        good_status, nfts = await xrpl_functions.get_nfts(user_obj['address'])
        if not good_status:
            return False
        serials = []
        t_serial = []
        e_serial = []

        for nft in nfts:

            if nft["Issuer"] in [ISSUER["Trainer"], ISSUER["TrainerV2"]]:
                serial = str(nft["nft_serial"])
                if serial in list(user_obj['trainer_cards'].keys()):
                    t_serial.append(serial)
                    continue
                print(serial, list(user_obj['trainer_cards'].keys()))
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
            if nft["Issuer"] == ISSUER["Zerpmon"]:
                serial = str(nft["nft_serial"])
                if serial in list(user_obj['zerpmons'].keys()):
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
            if nft["Issuer"] == ISSUER["Equipment"]:
                serial = str(nft["nft_serial"])
                if serial in list(user_obj['equipments'].keys()):
                    e_serial.append(serial)
                    continue
                print(serial, list(user_obj['equipments'].keys()))
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
        for serial in list(user_obj['zerpmons'].keys()):
            if serial not in serials:
                loaned = user_obj['zerpmons'][serial].get('loaned', False)
                if loaned:
                    serials.append(serial)
                else:
                    # if False:
                    db_query.remove_user_nft(user_obj['discord_id'], serial, False)
        for serial in list(user_obj['trainer_cards'].keys()):
            if serial not in t_serial:
                # if False:
                db_query.remove_user_nft(user_obj['discord_id'], serial, True)
        for serial in list(user_obj['equipments'].keys()):
            if serial not in e_serial:
                # if False:
                db_query.remove_user_nft(user_obj['discord_id'], serial, equipment=True)

        if len(user_obj['zerpmons']) > 0 or len(user_obj['trainer_cards']) > 0:
            if MAIN_GUILD == guild.id:
                try:
                    # await asyncio.sleep(1)
                    user = guild.get_member(int(user_obj['discord_id']))
                    if user is None:
                        user = await guild.fetch_member(int(user_obj['discord_id']))
                    print(guild, user)
                    if user is not None:
                        user_obj['guild_id'] = guild.id
                        if len(user_obj['zerpmons']) > 0:
                            try:
                                role = utils.get(guild.roles, name="Zerpmon Holder")
                                if role is not None:
                                    await user.add_roles(role)
                            except Exception as e:
                                print(f"USER already has the required role {traceback.format_exc()}")
                        if len(user_obj['trainer_cards']) > 0:
                            try:
                                role = utils.get(guild.roles, name="Trainer")
                                if role is not None:
                                    await user.add_roles(role)
                            except:
                                print("USER already has the required role")
                except Exception as e:
                    print(f"USER already has the required role {e}")
                await asyncio.sleep(2)

        db_query.update_user_decks(user_obj['address'], user_obj['discord_id'], serials, t_serial)
        return True
    except Exception as e:
        logging.error(f"ERROR while updating NFTs: {traceback.format_exc()}")
        return False