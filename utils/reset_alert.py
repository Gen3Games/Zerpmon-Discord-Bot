import asyncio
import logging
import time
import traceback
import nextcord
import config
import db_query
from utils.checks import get_next_ts, get_time_left_utc
from utils.xrpl_ws import get_balance, send_zrp, send_txn, send_nft
from xrpl_functions import get_zrp_balance


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


next_run = time.time() - 300
last_cache_embed = None


async def send_reset_message(client: nextcord.Client):
    global next_run, last_cache_embed
    db_query.choose_gym_zerp()
    while True:
        await asyncio.sleep(20)
        next_day_ts = get_next_ts()
        reset_time = next_day_ts - time.time()
        # print(reset_time)
        if reset_time < 60:
            await asyncio.sleep(60)
            db_query.choose_gym_zerp()
            gym_str = '\nLost Gyms and Gym Zerpmon refreshed for each Leader!\n'
            if db_query.get_gym_reset() - time.time() < 60:
                gym_str += '**Cleared Gyms** have been refreshed and progressed to next Stage as well!'
                db_query.set_gym_reset()
            guilds = client.guilds
            main_channel = None
            for guild in guilds:
                try:
                    channel = nextcord.utils.get(guild.channels, name="🌐│zerpmon-center")
                    await channel.send('@everyone, Global Missions, Zerpmon, Store prices restored.' + gym_str)
                    main_channel = channel
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
                await asyncio.sleep(5)
            all_users = db_query.get_all_users()
            for user in all_users:
                if 'gym' in user:
                    won_gyms = user['gym']['won']
                    for gym, obj in won_gyms.items():
                        if obj['next_battle_t'] < time.time() - 86300:
                            db_query.reset_gym(user['discord_id'], user['gym'], gym, lost=False, skipped=True)
                        else:
                            db_query.reset_gym(user['discord_id'], user['gym'], gym, lost=False)
                if 'rank' in user:
                    rnk = user['rank']['tier']
                    decay_tiers = config.TIERS[-2:]
                    if user['rank']['last_battle_t'] < time.time() - 86400 and rnk in decay_tiers:
                        db_query.update_rank(user['discord_id'], win=False, decay=True)
            active_loans, expired_loans = db_query.get_active_loans()
            offer_expired = [f"<@{_i['listed_by']['id']}> your loan listing for {_i['zerpmon_name']} has been deactivated\n" for _i in expired_loans]
            for loan in active_loans:
                """less than 5 seconds left to loan end"""
                if loan['loan_expires_at'] <= time.time():
                    db_query.remove_user_nft(loan['accepted_by']['id'], loan['serial'], )
                    ack = db_query.update_loanee(loan['zerp_data'], loan['serial'], {'id': None, 'username': None, 'address': None}, days=0, amount_total=0, loan_ended=True, discord_id=loan['accepted_by']['id'])
                    if ack:
                        if loan['loan_expires_at'] != 0:
                            await send_nft('loan', loan['listed_by']['address'], loan['token_id'])
                        if loan['expires_at'] <= time.time() or loan['loan_expires_at'] == 0:
                            db_query.remove_listed_loan(loan['zerpmon_name'], loan['listed_by']['id'])
                        else:
                            offer_expired.append(f"<@{loan['listed_by']['id']}> your loan listing for {loan['zerpmon_name']} has been deactivated\n")
                elif loan['expires_at'] <= time.time() and loan['accepted_by']['id'] is None:
                    db_query.remove_listed_loan(loan['zerpmon_name'], loan['listed_by']['id'])
                else:
                    if loan['xrp']:
                        await send_txn(loan['listed_by']['address'], loan['per_day_cost'], 'loan')
                    else:
                        await send_zrp(loan['listed_by']['address'], loan['per_day_cost'], 'loan')
                    db_query.decrease_loan_pending(loan['zerpmon_name'], loan['per_day_cost'])
            if len(offer_expired) > 0:
                expiry_msg = f'{", ".join(offer_expired)}Please use: `/loan relist` command to reactivate your Loan listing'
                await main_channel.send(content=f'**📢 Loan Announcement (Sell offer not active) 📢**\n{expiry_msg}',)
        print('here')
        if next_run < time.time():
            guilds = client.guilds
            print('here')
            for guild in guilds:
                try:
                    if guild.id in config.MAIN_GUILD:
                        # RANKED EMBED
                        top_players = db_query.get_ranked_players(0)
                        embed = CustomEmbed(color=0x8f71ff,
                                            title=f"👑 TRAINER RANKINGS LEADERBOARD 👑")
                        embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                        for i, user in enumerate(top_players):
                            battle_deck = user['battle_deck']['0']
                            zerp_msg = ('> Battle Zerpmons:\n'
                                        f'> \n') if len(battle_deck) > 0 else '> Battle Zerpmons:\n'
                            for index, v in battle_deck.items():
                                if index == "trainer":
                                    attrs = user['trainer_cards'][v]['attributes']
                                    emj = '🧙'
                                    for attr in attrs:
                                        if 'Trainer Number' in attr['trait_type']:
                                            emj = '⭐'
                                            break
                                        if attr['value'] == 'Legendary':
                                            emj = '🌟'
                                            break
                                    zerp_msg = f'> Main Trainer:\n' \
                                               f'> \n' \
                                               f'> {emj} {user["trainer_cards"][v]["name"]} {emj}\t[view](https://xrp.cafe/nft/{user["trainer_cards"][v]["token_id"]})\n' \
                                               f'> \n' + zerp_msg
                                else:
                                    zerp_msg += f'> ⭐ {user["zerpmons"][v]["name"]} ⭐\t[view](https://xrp.cafe/nft/{user["zerpmons"][v]["token_id"]})\n'
                            msg = '#{0:<4} {1:<25}'.format(user['ranked'], user['username'])

                            embed.add_field(name=f'{msg}', value=f"{zerp_msg}", inline=True)
                            embed.add_field(name=f"Tier: {user['rank']['tier']}",
                                            value=f"Points: `{user['rank']['points']}`", inline=True)
                            embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                        if last_cache_embed != embed.fields:
                            last_cache_embed = embed.fields
                            channel = [i for i in guild.channels if 'trainer-rankings' in i.name]
                            if len(channel) > 0:
                                channel = channel[0]
                                if config.RANK_MSG_ID is not None:
                                    try:
                                        msg_ = await channel.fetch_message(config.RANK_MSG_ID)
                                        await msg_.edit(embed=embed)
                                    except Exception as e:
                                        logging.error(f"ERROR in sending Rankings message: {traceback.format_exc()}")
                                        r_msg = await channel.send(embed=embed)
                                        config.RANK_MSG_ID = r_msg.id

                                else:
                                    r_msg = await channel.send(embed=embed)
                                    config.RANK_MSG_ID = r_msg.id
                        # GYM EMBED
                        top_players = db_query.get_gym_leaderboard(0)
                        embed = CustomEmbed(color=0x8f71ff,
                                            title=f"🌟 GYM RANKINGS LEADERBOARD 🌟")
                        embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                        for i, user in enumerate(top_players):
                            battle_deck = user.get('gym_deck', {'0': {}})['0']
                            zerp_msg = ('> Battle Zerpmons:\n'
                                        f'> \n') if len(battle_deck) > 0 else '> Battle Zerpmons:\n'
                            for index, v in battle_deck.items():
                                if index == "trainer":
                                    attrs = user['trainer_cards'][v]['attributes']
                                    emj = '🧙'
                                    for attr in attrs:
                                        if 'Trainer Number' in attr['trait_type']:
                                            emj = '⭐'
                                            break
                                        if attr['value'] == 'Legendary':
                                            emj = '🌟'
                                            break
                                    zerp_msg = f'> Main Trainer:\n' \
                                               f'> \n' \
                                               f'> {emj} {user["trainer_cards"][v]["name"]} {emj}\t[view](https://xrp.cafe/nft/{user["trainer_cards"][v]["token_id"]})\n' \
                                               f'> \n' + zerp_msg
                                else:
                                    zerp_msg += f'> ⭐ {user["zerpmons"][v]["name"]} ⭐\t[view](https://xrp.cafe/nft/{user["zerpmons"][v]["token_id"]})\n'
                            msg = '#{0:<4} {1:<25}'.format(user['ranked'], user['username'])

                            embed.add_field(name=f'{msg}', value=f"{zerp_msg}", inline=True)
                            embed.add_field(name=f"Tier: {user['rank_title']}",
                                            value=f"GP: `{user['gym']['gp']}`", inline=True)
                            embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                        channel = [i for i in guild.channels if 'gym-rankings' in i.name]
                        if len(channel) > 0:
                            channel = channel[0]
                            if config.GYM_MSG_ID is not None:
                                try:
                                    msg_ = await channel.fetch_message(config.GYM_MSG_ID)
                                    await msg_.edit(embed=embed)
                                except Exception as e:
                                    logging.error(f"ERROR in sending GYM Rankings message: {traceback.format_exc()}")
                                    r_msg = await channel.send(embed=embed)
                                    config.GYM_MSG_ID = r_msg.id

                            else:
                                r_msg = await channel.send(embed=embed)
                                config.GYM_MSG_ID = r_msg.id
                    channel = [i for i in guild.channels if 'Restore' in i.name]
                    h, m, s = await get_time_left_utc()
                    # print(channel, time.time()//1)
                    if len(channel) > 0:
                        channel = channel[0]
                        await channel.edit(name=f"⏰ Restore: {str(h).zfill(2)}:{str(m).zfill(2)}")

                    channel = [i for i in guild.channels if 'Mission XRP' in i.name]
                    bal = await get_balance(config.REWARDS_ADDR)
                    amount_to_send = bal * (config.MISSION_REWARD_XRP_PERCENT / 100)
                    # print(channel, time.time()//1)
                    if len(channel) > 0:
                        channel = channel[0]
                        await channel.edit(name=f"💰 Mission XRP: {amount_to_send:.4f}")
                        # await asyncio.sleep(5)
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
            try:
                store_bal = await get_zrp_balance(config.STORE_ADDR, )
                store_bal = round(float(store_bal), 2)
                if store_bal > 500:
                    await send_zrp(config.ISSUER['ZRP'], store_bal, 'store')
                loan_bal = db_query.get_loan_burn()
                loan_bal = round(float(loan_bal), 2)
                if loan_bal > 20:
                    sent_z = await send_zrp(config.ISSUER['ZRP'], loan_bal, 'loan')
                    if sent_z:
                        db_query.inc_loan_burn(-loan_bal)
            except Exception as e:
                logging.error(f'ERROR while burning ZRP: {traceback.format_exc()}')
            next_run = time.time() + 300
