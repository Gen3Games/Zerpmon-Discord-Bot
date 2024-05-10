import asyncio
import logging
import traceback
import xumm_functions
import nextcord
from nextcord import Interaction, utils
from config import ISSUER, MAIN_GUILD
import db_query
import xrpl_functions
import config
from globals import CustomEmbed


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

        if nft["Issuer"] == config.ISSUER["Trainer"]:

            metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])
            serial = nft["nft_serial"]
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
        if 'address' not in user_obj or len(user_obj['address']) < 5 or user_obj[
            'address'] == 'rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME':
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
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])
                if metadata is None:
                    continue

                if "Zerpmon" in metadata['description']:
                    t_serial.append(serial)
                    # Add to MongoDB here
                    new_z = {"name": metadata['name'],
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft["NFTokenID"],
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['discord_id'], serial, new_z, True)
                await asyncio.sleep(2)
            if nft["Issuer"] == ISSUER["Zerpmon"]:
                serial = str(nft["nft_serial"])
                if serial in list(user_obj['zerpmons'].keys()):
                    serials.append(serial)
                    continue
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])

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
                             'active_t': active_t,
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['discord_id'], serial, new_z, False)
                await asyncio.sleep(2)
            if nft["Issuer"] == ISSUER["Equipment"]:
                serial = str(nft["nft_serial"])
                if serial in list(user_obj['equipments'].keys()):
                    e_serial.append(serial)
                    continue
                print(serial, list(user_obj['equipments'].keys()))
                metadata = xrpl_functions.get_nft_metadata(nft['URI'], nft["NFTokenID"])

                if "Zerpmon Equipment" in metadata['description']:
                    e_serial.append(serial)
                    # Add to MongoDB here
                    new_z = {"name": metadata['name'],
                             "image": metadata['image'],
                             "attributes": metadata['attributes'],
                             "token_id": nft["NFTokenID"],
                             "type": get_type(metadata['attributes'])
                             }
                    await db_query.add_user_nft(user_obj['discord_id'], serial, new_z, equipment=True)
                await asyncio.sleep(2)
        for serial in list(user_obj['zerpmons'].keys()):
            if serial not in serials:
                loaned = user_obj['zerpmons'][serial].get('loaned', False)
                if loaned:
                    serials.append(serial)
                else:
                    # if False:
                    await db_query.remove_user_nft(user_obj['discord_id'], serial, False)
        for serial in list(user_obj['trainer_cards'].keys()):
            if serial not in t_serial:
                loaned = user_obj['trainer_cards'][serial].get('loaned', False)
                if loaned:
                    t_serial.append(serial)
                else:
                    await db_query.remove_user_nft(user_obj['discord_id'], serial, True)
        for serial in list(user_obj['equipments'].keys()):
            if serial not in e_serial:
                loaned = user_obj['equipments'][serial].get('loaned', False)
                if loaned:
                    e_serial.append(serial)
                else:
                    await db_query.remove_user_nft(user_obj['discord_id'], serial, equipment=True)

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

        await db_query.update_user_decks(user_obj['address'], user_obj['discord_id'], serials, t_serial, e_serial)
        return True
    except Exception as e:
        logging.error(f"ERROR while updating NFTs: {traceback.format_exc()}")
        return False
