import asyncio
import logging
import time
import traceback
import nextcord
import config
import db_query
from utils import battle_function
from utils.checks import get_next_ts, get_time_left_utc, get_days_left
from utils.xrpl_ws import get_balance, send_zrp, send_txn, send_nft
from xrpl_functions import get_zrp_balance


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


next_run = time.time() - 300
last_cache_embed = {'1v1': None, '3v3': None, '5v5': None}
boss_hp_cache = None


async def send_boss_update_msg(msg_channel: nextcord.TextChannel, edit_msg: bool):
    global boss_hp_cache

    boss_info = await db_query.get_boss_stats()
    boss_zerp = boss_info.get('boss_zerpmon')
    top_10 = await db_query.get_boss_leaderboard()
    embed = CustomEmbed(color=0x8f71ff,
                        title=f"{boss_zerp['name']} (🌟) has been summoned as the World Boss!")
    embed.set_image(
        boss_zerp['image'] if "https:/" in boss_zerp['image'] else 'https://cloudflare-ipfs.com/ipfs/' + boss_zerp[
            'image'].replace("ipfs://", ""))
    embed.add_field(name="Total HP 💚:", value=f"> **{boss_info['start_hp']}**", inline=False)
    embed.add_field(name="HP Left 💚:", value=f"> **{boss_info['boss_hp']}**", inline=False)
    embed.add_field(name="Reward Pool 💰:", value=f"> **{boss_info['reward']} ZRP**", inline=False)
    embed.add_field(name="Reset time 🕟:", value=f"> <t:{boss_info['boss_reset_t']}:R>", inline=False)
    embed.add_field(name='\u200B', value=f"\u200B", inline=False)

    embed.add_field(name='Top damage dealers  🏹', value=f"\u200B", inline=False)
    total_dmg = boss_info['total_weekly_dmg'] + boss_info['boss_hp']
    for idx, user in enumerate(top_10):
        dmg = user['boss_battle_stats'].get('weekly_dmg', 0)
        embed.add_field(name=f"#{idx + 1} {user['username']}",
                        value=f"> Damage dealt **{dmg}**\n"
                              f"> Max damage **{user['boss_battle_stats'].get('max_dmg', 0)}**\n"
                              f"> **ZRP share  `{max(0, round(dmg * boss_info['reward'] / total_dmg, 1)) if total_dmg > 0 else 0}`**",
                        inline=False)

    view = nextcord.ui.View(timeout=600)
    b1 = nextcord.ui.Button(label=f"View {boss_zerp['name']}", style=nextcord.ButtonStyle.green, )
    b1.callback = lambda i: battle_function.show_single_embed(i, boss_zerp['name'], omni=True)
    view.add_item(b1)
    if boss_hp_cache is None or boss_info['boss_hp'] != boss_hp_cache:
        boss_hp_cache = boss_info['boss_hp']
        try:
            if config.BOSS_MSG_ID:
                msg_ = await msg_channel.fetch_message(config.BOSS_MSG_ID)
            if edit_msg and config.BOSS_MSG_ID:
                await msg_.edit(embed=embed, view=view)
            else:
                if config.BOSS_MSG_ID:
                    await msg_.delete()
                n_msg = await msg_channel.send(content='@everyone', embed=embed, view=view)
                config.BOSS_MSG_ID = n_msg.id
                await db_query.set_boss_msg_id(n_msg.id)
        except Exception as e:
            logging.error(f"ERROR in sending boss embed update message: {traceback.format_exc()}")


async def send_reset_message(client: nextcord.Client):
    global next_run, last_cache_embed
    await db_query.choose_gym_zerp()
    while True:
        await asyncio.sleep(20)
        next_day_ts = await get_next_ts()
        reset_time = next_day_ts - time.time()
        # print(reset_time)
        if reset_time < 300:
            await asyncio.sleep(abs(reset_time))
            await db_query.choose_gym_zerp()
            gym_str = '\nLost Gyms and Gym Zerpmon refreshed for each Leader!\n'
            if await db_query.get_gym_reset() - time.time() < 60:
                gym_str += '**Cleared Gyms** have been refreshed and progressed to next Stage as well!'
                await db_query.set_gym_reset()
            guilds = client.guilds
            main_channel = None
            boss_channel = None
            for guild in guilds:
                try:
                    channel = nextcord.utils.get(guild.channels, name="🌐│zerpmon-center")
                    await channel.send('@everyone, Global Missions, Zerpmon, Store prices restored.' + gym_str)
                    if guild.id in config.MAIN_GUILD:
                        main_channel = nextcord.utils.get(guild.channels, id=1154376146985697391)
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
                await asyncio.sleep(5)
            all_users = await db_query.get_all_users()
            for user in all_users:
                try:
                    if 'gym' in user:
                        won_gyms = user['gym'].get('won', {})
                        for gym, obj in won_gyms.items():
                            if obj['next_battle_t'] < time.time() - 86300:
                                await db_query.reset_gym(user['discord_id'], user['gym'], gym, lost=False, skipped=True)
                            else:
                                await db_query.reset_gym(user['discord_id'], user['gym'], gym, lost=False)
                    for r_key in ['rank', 'rank1', 'rank5']:
                        if r_key in user:
                            rnk = user[r_key]['tier']
                            decay_tiers = config.TIERS[-2:]
                            if user[r_key]['last_battle_t'] < time.time() - 86400 and rnk in decay_tiers:
                                await db_query.update_rank(user['discord_id'], win=False, decay=True, field=r_key)
                except:
                    logging.error(f'USER OBJ ERROR: {traceback.format_exc()}')
            active_loans, expired_loans = await db_query.get_active_loans()
            offer_expired = [
                f"<@{_i['listed_by']['id']}> your loan listing for {_i['zerpmon_name']} has been deactivated\n" for _i
                in expired_loans]
            try:
                for loan in active_loans:
                    """less than 5 seconds left to loan end"""
                    if loan['loan_expires_at'] <= time.time():
                        await db_query.remove_user_nft(loan['accepted_by']['id'], loan['serial'], )
                        ack = await db_query.update_loanee(loan['zerp_data'], loan['serial'],
                                                     {'id': None, 'username': None, 'address': None}, days=0,
                                                     amount_total=0, loan_ended=True,
                                                     discord_id=loan['accepted_by']['id'])
                        if ack:
                            if loan['loan_expires_at'] != 0:
                                await send_nft('loan', loan['listed_by']['address'], loan['token_id'])
                            if loan['expires_at'] <= time.time() or loan['loan_expires_at'] == 0:
                                await db_query.remove_listed_loan(loan['zerpmon_name'], loan['listed_by']['id'])
                            else:
                                offer_expired.append(
                                    f"<@{loan['listed_by']['id']}> your loan listing for {loan['zerpmon_name']} has been deactivated\n")
                    elif loan['expires_at'] <= time.time() and loan['accepted_by']['id'] is None:
                        await db_query.remove_listed_loan(loan['zerpmon_name'], loan['listed_by']['id'])
                    else:
                        if loan['xrp']:
                            await send_txn(loan['listed_by']['address'], loan['per_day_cost'], 'loan', memo=f'{loan["zerpmon_name"]} loan payment')
                        else:
                            await send_zrp(loan['listed_by']['address'], loan['per_day_cost'], 'loan', memo=f'{loan["zerpmon_name"]} loan payment')
                        await db_query.decrease_loan_pending(loan['zerpmon_name'], loan['per_day_cost'])
                if len(offer_expired) > 0:
                    expiry_msg = f'{", ".join(offer_expired)}Please use: `/loan relist` command to reactivate your Loan listing'
                    await main_channel.send(
                        content=f'**📢 Loan Announcement (Sell offer not active) 📢**\n{expiry_msg}', )
            except:
                pass
        print('here')
        if next_run < time.time():
            guilds = client.guilds
            print('here')
            for guild in guilds:
                try:
                    if guild.id in config.MAIN_GUILD:
                        # TOWER EMBED
                        users = await db_query.get_tower_rush_leaderboard(None)
                        embed = CustomEmbed(color=0xa56cc1,
                                            title=f"TOWER RUSH LEADERBOARD")

                        for i, user in users:
                            msg = '#{0:<4} {1:<25} TRP : {3:>2}      Highest level reached: {2:<20}'.format(i, user['username'],
                                                                                                 user.get('max_level', 1),
                                                                                                 user['tp'])
                            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
                        tower_channel = nextcord.utils.get(guild.channels, id=config.TOWER_CHANNEL)
                        if config.TOWER_MSG_ID:
                            try:
                                msg_ = await tower_channel.fetch_message(config.TOWER_MSG_ID)
                                await msg_.edit(embed=embed)
                            except Exception as e:
                                logging.error(f"ERROR in sending TOWER Rankings message: {traceback.format_exc()}")
                                r_msg = await tower_channel.send(embed=embed)
                                config.TOWER_MSG_ID = r_msg.id
                        else:
                            r_msg = await tower_channel.send(embed=embed)
                            config.TOWER_MSG_ID = r_msg.id
                        # BOSS EMBED
                        if config.zerpmon_holders > 0:
                            boss_channel = nextcord.utils.get(guild.channels, id=config.BOSS_CHANNEL)
                            config.boss_active, _, config.boss_reset_t, config.BOSS_MSG_ID, new = await db_query.get_boss_reset(
                                config.zerpmon_holders * config.BOSS_HP_PER_USER)
                            await send_boss_update_msg(boss_channel, not new, )
                        # RANKED EMBED
                        top_players_1 = await db_query.get_ranked_players(0, field='rank1')
                        top_players_3 = await db_query.get_ranked_players(0)
                        top_players_5 = await db_query.get_ranked_players(0, field='rank5')
                        ranking_obj = {'1v1': [1164574314922791022, top_players_1],
                                       '3v3': [1164574346430386207, top_players_3],
                                       '5v5': [1164574379884150925, top_players_5]}
                        for leaderboard in ranking_obj:
                            z_len = int(leaderboard[0])
                            embed = CustomEmbed(color=0x8f71ff,
                                                title=f"👑 TRAINER RANKINGS LEADERBOARD {leaderboard} 👑")
                            embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                            for i, user in enumerate(ranking_obj[leaderboard][1]):
                                # print(user)
                                battle_d = user.get('battle_deck', {'0': {}}).get('0', {})
                                recent_key = 'recent_deck' if z_len == 3 else 'recent_deck' + str(z_len)
                                battle_deck = user.get(recent_key, battle_d)
                                shorted_deck = {}
                                if 'trainer' in battle_deck:
                                    shorted_deck['trainer'] = battle_deck['trainer']
                                for k in range(z_len):
                                    try:
                                        shorted_deck[str(k)] = battle_deck[str(k)]
                                    except:
                                        pass
                                zerp_msg = ('> Battle Zerpmons:\n'
                                            f'> \n') if len(battle_deck) > 0 else '> Battle Zerpmons:\n'
                                for index, v in shorted_deck.items():
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
                                user_r_d = user[
                                    'rank' if leaderboard == '3v3' else ('rank5' if leaderboard == '5v5' else 'rank1')]
                                embed.add_field(name=f"Tier: {user_r_d['tier']}",
                                                value=f"Points: `{user_r_d['points']}`", inline=True)
                                embed.add_field(name='\u200B', value=f"\u200B", inline=False)
                            if last_cache_embed[leaderboard] != embed.fields:
                                last_cache_embed[leaderboard] = embed.fields
                                channel = [i for i in guild.channels if i.id == ranking_obj[leaderboard][0]]
                                if len(channel) > 0:
                                    channel = channel[0]
                                    if config.RANK_MSG_ID[leaderboard] is not None:
                                        try:
                                            msg_ = await channel.fetch_message(config.RANK_MSG_ID[leaderboard])
                                            await msg_.edit(embed=embed)
                                        except Exception as e:
                                            logging.error(
                                                f"ERROR in sending Rankings message: {traceback.format_exc()}")
                                            r_msg = await channel.send(embed=embed)
                                            config.RANK_MSG_ID[leaderboard] = r_msg.id

                                    else:
                                        r_msg = await channel.send(embed=embed)
                                        config.RANK_MSG_ID[leaderboard] = r_msg.id
                        # GYM EMBED
                        top_players = await db_query.get_gym_leaderboard(0)
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
                    channel = [i for i in guild.channels if 'Season Ends' in i.name]
                    if len(channel) > 0:
                        channel = channel[0]
                        await channel.edit(name=f"Season Ends in {get_days_left(config.SEASON_END_TS)} days")
                        # await asyncio.sleep(5)
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
            try:
                store_bal = await get_zrp_balance(config.STORE_ADDR, )
                store_bal = round(float(store_bal), 2)
                if store_bal > 500:
                    await send_zrp(config.ISSUER['ZRP'], store_bal, 'store')
                loan_bal = await db_query.get_loan_burn()
                loan_bal = round(float(loan_bal), 2)
                if loan_bal > 20:
                    sent_z = await send_zrp(config.ISSUER['ZRP'], loan_bal, 'loan')
                    if sent_z:
                        await db_query.inc_loan_burn(-loan_bal)
            except Exception as e:
                logging.error(f'ERROR while burning ZRP: {traceback.format_exc()}')
            next_run = time.time() + 300
