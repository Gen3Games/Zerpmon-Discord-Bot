import logging
import random
import time
import traceback
from nextcord import Interaction, Message, TextChannel, Embed
import config
import db_query
from utils import battle_function
from collections import deque


class CustomEmbed(Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


async def do_matches(channel_id: int, msg: Message, participants=None):
    winners = deque()
    # i = config.battle_royale_participants[0].copy()
    # i['id'], i['username'] = '228969462785638410', '228969462785638410'
    # i2 = config.battle_royale_participants[1].copy()
    # i2['id'], i2['username'] = '288409001274638337', '288409001274638337'
    # config.battle_royale_participants.append(i)
    # config.battle_royale_participants.append(i2)
    all_players = participants if participants else config.battle_royale_participants
    count = len(all_players)
    schedule_str = ""
    round_n = 1
    i = 0
    while i < count:
        winners.appendleft(all_players[i])
        if i+1 < count:
            winners.appendleft(all_players[i+1])
            schedule_str += f"**Match #{(i+2)//2}**:\n{all_players[i]['username']} vs {all_players[i+1]['username']}\n\n"
        else:
            schedule_str += f"**Match #{(i+2)//2}**:\n{all_players[i]['username']} vs Revived Player?\n\n"
        i += 2

    await msg.reply(embed=CustomEmbed(title=f"Round {round_n}", color=0xe0ffcd, description=schedule_str))

    losers = []
    while len(winners) > 1:
        size = len(winners)
        print(losers)
        old_losers = losers.copy()
        losers = []
        for i in range((size+1)//2):
            p1 = winners.pop()
            if size > 1:
                p2 = winners.pop()
            else:
                try:
                    p2 = random.choice(losers)
                except:
                    p2 = random.choice(old_losers)
                await msg.channel.send(
                    f"It's a miracle! {p2['zerp_name']} was brought back from the dead")
            size -= 2
            config.ongoing_battles.append(p1['id'])
            config.ongoing_battles.append(p2['id'])

            battle_instance = {
                "type": 'friendly',
                "challenger": p1['id'],
                "username1": p1['username'],
                "challenged": p2['id'],
                "username2": p2['username'],
                "active": True,
                "channel_id": channel_id,
                "timeout": time.time() + 60,
                'battle_type': 1,
            }
            config.battle_dict[msg.id] = battle_instance

            try:

                winner = await battle_function.proceed_battle(msg, battle_instance,
                                                              battle_instance['battle_type'],
                                                              battle_name='Battle Royale')
                p1['zerp_name'] = battle_instance['z1_name']
                p2['zerp_name'] = battle_instance['z2_name']
                if winner == 1:
                    winners.appendleft(p1)
                    losers.append(p2)
                elif winner == 2:
                    winners.appendleft(p2)
                    losers.append(p1)
            except Exception as e:
                logging.error(f"ERROR during friendly battle R: {e}\n{traceback.format_exc()}")
            finally:
                config.ongoing_battles.remove(p1['id'])
                config.ongoing_battles.remove(p2['id'])
                del config.battle_dict[msg.id]

        if len(winners) != 1:
            count = len(winners)
            schedule_str = ""
            i = 0
            while i < count:
                if i + 1 < count:
                    schedule_str += f"**Match #{(i + 2) // 2}**:\n{winners[i]['username']} vs {winners[i + 1]['username']}\n\n"
                else:
                    schedule_str += f"**Match #{(i + 2) // 2}**:\n{winners[i]['username']} vs Revived Player?\n\n"
                i += 2
            round_n += 1
            await msg.reply(embed=CustomEmbed(title=f"Round {round_n}", color=0xe0ffcd, description=schedule_str))
    if not participants:
        config.battle_royale_participants = [winners.pop()]
        return None
    else:
        return winners


async def start_global_br(battle_channel: TextChannel):
    participants = config.global_br_participants.copy()
    config.global_br_participants = []
    # db_query.save_br_dict([])
    try:
        msg = await battle_channel.send(content="Battle **beginning**")
        winners = await do_matches(battle_channel.id, msg, participants=participants)

        await msg.channel.send(
            f"**CONGRATULATIONS** **{winners[0]['username']}** on winning the Battle Royale!")

    except Exception as e:
        logging.error(f'Error in battleR: {traceback.format_exc()}')
