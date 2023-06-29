import asyncio
import logging
import time
import traceback

import nextcord

import config
import db_query
from utils.checks import get_next_ts, get_time_left_utc


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


next_run = time.time() - 300
last_cache_embed = None


async def send_reset_message(client: nextcord.Client):
    global next_run, last_cache_embed
    while True:
        await asyncio.sleep(20)
        reset_time = get_next_ts() - time.time()
        # print(reset_time)
        if reset_time < 60:
            await asyncio.sleep(60)
            guilds = client.guilds
            for guild in guilds:
                try:
                    channel = nextcord.utils.get(guild.channels, name="🌐│zerpmon-center")
                    await channel.send('@everyone, Global Missions, Zerpmon, Store prices restored.')
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
                await asyncio.sleep(5)
            all_users = db_query.get_all_users()
            for user in all_users:
                if 'rank' not in user:
                    continue
                rnk = user['rank']['tier']
                decay_tiers = config.TIERS[-2:]
                if user['rank']['last_battle_t'] < time.time() - 84600 and rnk in decay_tiers:
                    db_query.update_rank(user['discord_id'], win=False, decay=True)
        print('here')
        if next_run < time.time():
            next_run = time.time() + 300
            guilds = client.guilds
            print('here')
            for guild in guilds:
                try:
                    if guild.id in config.MAIN_GUILD:
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
                                    zerp_msg = f'> Main Trainer:\n' \
                                               f'> \n' \
                                               f'> 🧙 {user["trainer_cards"][v]["name"]} 🧙\n' \
                                               f'> \n' + zerp_msg
                                else:
                                    zerp_msg += f'> ⭐ {user["zerpmons"][v]["name"]} ⭐\n'
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

                    channel = [i for i in guild.channels if 'Restore' in i.name]
                    h, m, s = await get_time_left_utc()
                    # print(channel, time.time()//1)
                    if len(channel) > 0:
                        channel = channel[0]
                        await channel.edit(name=f"⏰ Restore: {str(h).zfill(2)}:{str(m).zfill(2)}")
                        # await asyncio.sleep(5)
                except Exception as e:
                    logging.error(f'ERROR: {traceback.format_exc()}')
