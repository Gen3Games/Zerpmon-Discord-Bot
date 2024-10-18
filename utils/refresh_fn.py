import asyncio
import logging
import traceback

from xrpl.core.addresscodec import is_valid_classic_address

import xumm_functions
import nextcord
from nextcord import Interaction, utils
from config import ISSUER, MAIN_GUILD
import db_query
import xrpl_functions
import config
from globals import CustomEmbed
from rootTest import zerp_collection_id, trainer_collection_id, eq_collection_id, getOwnedRootNFTs, get_trn_staked_nfts


def get_type(attrs):
    types = []
    try:
        for i in attrs:
            if i['trait_type'] in ['Type', 'Affinity']:
                types.append(i['value'].lower().title())
    except:
        print(traceback.format_exc())
    return types


async def post_signin_callback(interaction: nextcord.Interaction, address: str, z_role=None, t_role=None):
    if z_role is None:
        roles = interaction.guild.roles
        z_role = nextcord.utils.get(roles, name="Zerpmon Holder")
        t_role = nextcord.utils.get(roles, name="Trainer")
    # Sanity check (Dual Discord Account with 1 Wallet)
    wallet_exist = await db_query.check_wallet_exist(address)
    if wallet_exist:
        await interaction.send(f"This wallet address has already been verified!")
        return False
    # Proceed

    good_status, nfts = await xrpl_functions.get_nfts(address)

    user_obj = {
        "username": interaction.user.name + "#" + interaction.user.discriminator,
        "discord_id": str(interaction.user.id),
        "guild_id": interaction.guild_id,
        "zerpmons": {},
        "trainer_cards": {},
        "equipments": {},
        "battle_deck": {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}},
        "gym_deck": {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}},
    }

    if not good_status:
        # In case the account isn't active or XRP server is down
        await interaction.send(f"**Sorry, encountered an Error!**", ephemeral=True)
        return False

    for nft in nfts:

        if nft["Issuer"] in [ISSUER["Trainer"], ISSUER["TrainerV2"], ISSUER['Legend']]:
            serial = nft["nft_serial"]
            if nft["Issuer"] == ISSUER['Legend']:
                serial = 'legends' + serial
            metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])

            if metadata and "Zerpmon Trainers" in metadata['description']:
                # Add to MongoDB here
                user_obj["trainer_cards"][serial] = {"name": metadata['name'],
                                                     "image": metadata['image'],
                                                     "attributes": metadata['attributes'],
                                                     "token_id": nft["NFTokenID"],
                                                     "type": get_type(metadata['attributes'])
                                                     }

        if nft["Issuer"] == config.ISSUER["Zerpmon"]:
            metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])
            serial = nft["nft_serial"]
            if metadata and "Zerpmon " in metadata['description']:
                # Add to MongoDB here
                user_obj["zerpmons"][serial] = {"name": metadata['name'],
                                                "image": metadata['image'],
                                                "attributes": metadata['attributes'],
                                                "token_id": nft["NFTokenID"],
                                                "type": get_type(metadata['attributes'])
                                                }
        if nft["Issuer"] == config.ISSUER["Equipment"]:
            metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])
            serial = nft["nft_serial"]
            if metadata and "Zerpmon Equipment" in metadata['description']:
                # Add to MongoDB here
                user_obj["equipments"][serial] = {"name": metadata['name'],
                                                  "image": metadata['image'],
                                                  "attributes": metadata['attributes'],
                                                  "token_id": nft["NFTokenID"],
                                                  "type": get_type(metadata['attributes'])
                                                  }
    if len(user_obj['zerpmons']) > 0:
        await interaction.user.add_roles(z_role)
    if len(user_obj['trainer_cards']) > 0:
        await interaction.user.add_roles(t_role)
    # Save the address to stop dual accounts
    user_obj['address'] = address
    await db_query.save_user(user_obj)
    for k in ['gym_deck', 'battle_deck', 'mission_deck']:
        if k != 'mission_deck':
            for i in range(5):
                await db_query.set_equipment_on(user_obj['discord_id'], [None, None, None, None, None], k, str(i))
        else:
            await db_query.set_equipment_on(user_obj['discord_id'], [None, None, None, None, None] * 4, k, None)
    return True


async def verify_wallet(interaction: nextcord.Interaction, force=False):
    roles = interaction.guild.roles
    z_role = nextcord.utils.get(roles, name="Zerpmon Holder")
    t_role = nextcord.utils.get(roles, name="Trainer")
    if not force and (z_role in interaction.user.roles or t_role in interaction.user.roles):
        await interaction.send(f"You are already verified!")
        return

    # Proceed
    await interaction.send(f"Generating a QR code", ephemeral=True)

    uuid, url, href = await xumm_functions.gen_signIn_url()
    embed = CustomEmbed(color=0x01f39d, title=f"Please sign in using this QR code or click here.",
                        url=href)

    embed.set_image(url=url)

    msg = await interaction.send(embed=embed, ephemeral=True, )
    for i in range(120):
        logged_in, address = await xumm_functions.check_sign_in(uuid)

        if logged_in:
            await interaction.send(f"**Signed in successfully!**", ephemeral=True)
            return await post_signin_callback(interaction, address, z_role, t_role)
        await asyncio.sleep(1)
    await msg.edit(embed=CustomEmbed(title="QR code **expired** please generate a new one.", color=0x000))
    return False


async def refresh_nfts(interaction: Interaction, user_doc, old_address=None):
    guild = interaction.guild
    if old_address is not None:
        if not await db_query.update_address(user_doc['address'], old_address):
            return False
    user_obj = user_doc

    try:
        if 'address' not in user_obj or len(user_obj['address']) < 5 or \
                user_obj['address'] == 'rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME':
            return False
        xrpl_addresses, root_addresses = [], []
        linked_addresses = [*user_obj['linked_addresses'], user_obj['address']] if \
            'linked_addresses' in user_obj else [user_obj['address']]
        good_status_xrpl, good_status_trn, nfts = True, True, []
        for addr in linked_addresses:
            if is_valid_classic_address(addr):
                xrpl_addresses.append(addr)
            else:
                root_addresses.append(addr)
        root_task = asyncio.create_task(getOwnedRootNFTs(root_addresses))
        for addr in xrpl_addresses:
            success, found_nfts = await xrpl_functions.get_nfts(addr)
            if not success:
                good_status_xrpl = False
                break
            nfts.extend(found_nfts)
        """Also append staked nfts"""
        nfts.extend(await db_query.get_xrpl_staked_nfts(xrpl_addresses))
        # 1 min timeout
        success, found_root_nfts = await asyncio.wait_for(root_task, timeout=60)
        if not success:
            good_status_trn = False
        staked_nfts = await get_trn_staked_nfts(root_addresses)
        # print(staked_nfts)
        if staked_nfts is None:
            good_status_trn = False
        for addr, obj in found_root_nfts.items():
            for token in staked_nfts['zerpmons']:
                if obj[zerp_collection_id]:
                    obj[zerp_collection_id].append(token)
                else:
                    obj[zerp_collection_id]=[token]
            for token in staked_nfts['trainers']:
                if obj[trainer_collection_id]:
                    obj[trainer_collection_id].append(token)
                else:
                    obj[trainer_collection_id] = [token]
            for token in staked_nfts['eqs']:
                if obj[eq_collection_id]:
                    obj[eq_collection_id].append(token)
                else:
                    obj[eq_collection_id] = [token]
            break
        # print(found_root_nfts)
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
        if not good_status_xrpl:
            for sr in user_obj['zerpmons']:
                if not str(sr).startswith('trn-'):
                    serials.append(sr)
            for sr in user_obj['trainer_cards']:
                if not str(sr).startswith('trn-'):
                    t_serial.append(sr)
            for sr in user_obj['equipments']:
                if not str(sr).startswith('trn-'):
                    e_serial.append(sr)
        else:
            # Filter fn
            await filter_nfts(user_obj, nfts, serials, t_serial, e_serial)
        if not good_status_trn:
            for sr in user_obj['zerpmons']:
                if str(sr).startswith('trn-'):
                    serials.append(sr)
            for sr in user_obj['trainer_cards']:
                if str(sr).startswith('trn-'):
                    t_serial.append(sr)
            for sr in user_obj['equipments']:
                if str(sr).startswith('trn-'):
                    e_serial.append(sr)
        else:
            await filter_nfts(user_obj, found_root_nfts, serials, t_serial, e_serial, chain='trn')

        for serial in list(user_obj['zerpmons'].keys()):
            if serial not in serials:
                loaned = user_obj['zerpmons'][serial].get('loaned', False)
                if loaned:
                    serials.append(serial)
                else:
                    # if False:
                    remove_serials['zerpmons'].append(serial)
        for serial in list(user_obj['trainer_cards'].keys()):
            if serial not in t_serial:
                loaned = user_obj['trainer_cards'][serial].get('loaned', False)
                if loaned:
                    t_serial.append(serial)
                else:
                    remove_serials['trainer_cards'].append(serial)
        for serial in list(user_obj['equipments'].keys()):
            if serial not in e_serial:
                loaned = user_obj['equipments'][serial].get('loaned', False)
                if loaned:
                    e_serial.append(serial)
                else:
                    remove_serials['equipments'].append(serial)

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

        await db_query.update_user_decks(user_obj, user_obj['discord_id'], serials, t_serial, e_serial, remove_serials)
        return True
    except Exception as e:
        logging.error(f"ERROR while updating NFTs: {traceback.format_exc()}")
        return False


GRYLL_ISSUER = "rGRLwjCy5JvvVHuWQNQm6mxovotPLMhuP6"


async def filter_nfts(user_obj, nfts, serials, t_serial, e_serial, chain='xrpl'):
    """Note:
    TRN serial format **trn-{token_id}**

    TRN nft_id format **trn-{collection_id}-{token_id}**
    """
    xahau = chain == 'xahau'
    owned_z_serials = list(user_obj['zerpmons'].keys())
    owned_t_serials = list(user_obj['trainer_cards'].keys())
    owned_eq_serials = list(user_obj['equipments'].keys())
    if xahau:
        serial_key = "index"
        token_id_key = "index"
    else:
        serial_key = "nft_serial"
        token_id_key = "NFTokenID"
    if chain == 'trn':
        """
        """
        for addr, obj in nfts.items():
            if obj[zerp_collection_id]:
                for token_id in obj[zerp_collection_id]:
                    nft_id = f"trn-{zerp_collection_id}-{token_id}"
                    serial = f"trn-{token_id}"
                    if serial in owned_z_serials:
                        serials.append(serial)
                        continue
                    metadata = xrpl_functions.get_nft_metadata(token_id, nft_id)
                    if metadata is None:
                        logging.error(f"Unable to find TRN metadata for {nft_id}")
                        continue
                    serials.append(serial)

                    active_t = 0
                    # Add to MongoDB here
                    new_z = {"name": f"{metadata['name']} #{token_id}",
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft_id,
                             'active_t': active_t,
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['address'], serial, new_z, False)
                    await asyncio.sleep(0.5)
            if obj[trainer_collection_id]:
                for token_id in obj[trainer_collection_id]:
                    nft_id = f"trn-{trainer_collection_id}-{token_id}"
                    serial = f"trn-{token_id}"
                    if serial in owned_t_serials:
                        t_serial.append(serial)
                        continue
                    metadata = xrpl_functions.get_nft_metadata(token_id, nft_id)
                    if metadata is None:
                        logging.error(f"Unable to find TRN metadata for {nft_id}")
                        continue
                    t_serial.append(serial)
                    # Add to MongoDB here
                    new_z = {"name": f"{metadata['name']} #{token_id}",
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft_id,
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['address'], serial, new_z, True)
                    await asyncio.sleep(0.5)
            if obj[eq_collection_id]:
                for token_id in obj[eq_collection_id]:
                    nft_id = f"trn-{eq_collection_id}-{token_id}"
                    serial = f"trn-{token_id}"
                    if serial in owned_eq_serials:
                        e_serial.append(serial)
                        continue
                    metadata = xrpl_functions.get_nft_metadata(token_id, nft_id)
                    if metadata is None:
                        logging.error(f"Unable to find TRN metadata for {nft_id}")
                        continue
                    e_serial.append(serial)
                    # Add to MongoDB here
                    new_z = {"name": f"{metadata['name']}",
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft_id,
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['address'], serial, new_z, equipment=True)
                    await asyncio.sleep(0.5)

    else:
        for nft in nfts:
            if "Issuer" not in nft:
                continue
            if nft["Issuer"] in [ISSUER["Trainer"], ISSUER["TrainerV2"], ISSUER['Legend'], GRYLL_ISSUER]:
                serial = ('xahau-' if xahau else '') + str(nft[serial_key])
                if nft["Issuer"] == ISSUER['Legend']:
                    serial = 'legends-' + serial
                elif nft["Issuer"] == GRYLL_ISSUER:
                    serial = 'gryll-' + serial
                if serial in owned_t_serials:
                    t_serial.append(serial)
                    continue
                print(serial, list(user_obj['trainer_cards'].keys()))
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft[token_id_key])
                if metadata is None:
                    continue

                # if "Zerpmon" in metadata['description']:
                t_serial.append(serial)
                # Add to MongoDB here
                new_z = {"name": metadata['name'],
                         "image": metadata['image'],
                         "attributes": metadata['attributes'],
                         "token_id": nft[token_id_key],
                         "type": get_type(metadata['attributes'])
                         }
                await db_query.add_user_nft(user_obj['address'], serial, new_z, True)
                await asyncio.sleep(1)
            if nft["Issuer"] == ISSUER["Zerpmon"]:
                serial = ('xahau-' if xahau else '') + str(nft[serial_key])
                if serial in owned_z_serials:
                    serials.append(serial)
                    continue
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft[token_id_key])
                if metadata is None:
                    continue
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
                             "token_id": nft[token_id_key],
                             'active_t': active_t,
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['address'], serial, new_z, False)
                await asyncio.sleep(1)
            if nft["Issuer"] == ISSUER["Equipment"]:
                serial = ('xahau-' if xahau else '') + str(nft[serial_key])
                if serial in owned_eq_serials:
                    e_serial.append(serial)
                    continue
                print(serial, list(user_obj['equipments'].keys()))
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft[token_id_key])
                if metadata is None:
                    continue
                if "Zerpmon Equipment" in metadata['description']:
                    e_serial.append(serial)
                    # Add to MongoDB here
                    new_z = {"name": metadata['name'],
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft[token_id_key],
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['address'], serial, new_z, equipment=True)
                await asyncio.sleep(1)
