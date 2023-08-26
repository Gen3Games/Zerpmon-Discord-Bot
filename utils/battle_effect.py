import inspect
import random
import re

import config


def get_crit_chance(effect):
    crit_chance = config.CRIT_CHANCES.copy()
    if 'increase' in effect and 'crit' in effect:
        match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
        val = int(float(match.group()))
        crit_chance[True] += val
    return random.choices(list(crit_chance.keys()),
                          list(crit_chance.values()))[0]


def update_dmg(dmg1, dmg2, status_affect_solo):
    changed_1, changed_2 = False, False
    for effect in status_affect_solo.copy():
        if not changed_2 and dmg2 != '' and dmg2 != 0 and 'next attack' in effect and 'damage' in effect and (
                'oppo' in effect or 'enemy' in effect):
            match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
            val = int(float(match.group()))
            dmg2 = (1 - (val / 100)) * dmg2
            changed_2 = True
            status_affect_solo.remove(effect)
        elif not changed_1 and dmg1 != '' and dmg1 != 0 and 'next attack' in effect and 'damage' in effect and not (
                'oppo' in effect or 'enemy' in effect):
            match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
            val = int(float(match.group()))
            dmg1 = (1 + (val / 100)) * dmg1
            changed_1 = True
            status_affect_solo.remove(effect)
    return dmg1, dmg2, status_affect_solo


def update_next_atk(p1, p2, index1, index2, status_affect_solo):
    p1 = p1[:]
    p2 = p2[:]
    for effect in status_affect_solo.copy():
        if 'damage' in effect:
            continue
        if 'next attack' in effect and index2 < 4 and ('oppo' in effect or 'enemy' in effect):
            match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
            val = int(float(match.group()))
            val = val if 'increase' in effect else -val
            p2 = update_array(p2, index2, val)
            status_affect_solo.remove(effect)

        elif 'next attack' in effect and index1 < 4 and not ('oppo' in effect or 'enemy' in effect):
            match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
            val = int(float(match.group()))
            val = val if 'increase' in effect else -val
            p1 = update_array(p1, index1, val)
            status_affect_solo.remove(effect)

    print(p1, p2, status_affect_solo)
    return p1, p2, status_affect_solo


def update_next_dmg(status_affect_solo):
    for effect in status_affect_solo.copy():
        if '0 damage' in effect:
            return 0, status_affect_solo
    return 1, status_affect_solo


def update_purple_stars(total, status_affect_solo):
    for effect in status_affect_solo.copy():
        if total == 0:
            break
        if 'reduce' in effect and 'star' in effect:
            if 'to 0' in effect:
                total = 0
            else:
                match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
                val = int(float(match.group()))
                total -= val
    return total, status_affect_solo


def update_array(arr, index, value, own=False):
    caller_name = inspect.currentframe().f_back.f_code.co_name
    print("Caller function:", caller_name)
    print('ARR RECV: ', arr)

    if arr[index] is None:
        return arr
    # Distribute the value change among the other elements
    remaining_value = -value

    if value < 0 and abs(value) > arr[index]:
        remaining_value = arr[index]
    if value < 0 and arr[-1] is not None and not own:
        arr[index] -= remaining_value
        arr[-1] += remaining_value
        print('ARR RET: ', arr)
        return arr

    # if value > 0 and value
    _i = len([i for i in arr if i is not None]) - 1
    for i in range(len(arr)):
        if arr[i] is None:
            continue
        if i != index:
            delta = remaining_value / _i
            _i -= 1
            arr[i] = round(arr[i] + delta, 2)

            if arr[i] < 0:
                remaining_value += arr[i]
                arr[i] = 0
            remaining_value -= delta

    # Set the index value to the desired value
    arr[index] += value
    if arr[index] >= 100:
        arr = [0 if (i != index and i is not None) else (100 if i == index else arr[i]) for i in range(len(arr))]
        print('ARR RET: ', arr)
        return arr
    # Check if any values are out of bounds (i.e. negative or greater than 100)
    for i in range(len(arr)):
        if arr[i] is None:
            continue
        if arr[i] < 0:
            arr[i] = 0
        elif arr[i] > 100:
            arr[i] = 100
    print('ARR RET: ', arr)
    return arr


def apply_status_effects(p1, p2, status_e):
    print(f'old: {p1, p2}, {status_e}')

    p1_atk = [i for i in p1[:4] if i is not None]
    low_index1 = p1.index(min(p1_atk))
    l_color1 = 'white' if low_index1 in [0, 1] else ('gold' if low_index1 in [2, 3] else 'purple')
    max_index1 = p1.index(max(p1_atk))
    m_color1 = 'white' if max_index1 in [0, 1] else ('gold' if max_index1 in [2, 3] else 'purple')
    try:
        l_val = min([i for i in p1[2:4] if i is not None])
        lg_index1 = [index for index, value in enumerate(p1) if value == l_val and index >= 2 and index < 4][0]
        g_val = max([i for i in p1[2:4] if i is not None])
        mg_index1 = [index for index, value in enumerate(p1) if value == g_val and index >= 2 and index < 4][0]
    except:
        lg_index1 = 2
        mg_index1 = 2

    p2_atk = [i for i in p2[:4] if i is not None]
    low_index2 = p2.index(min(p2_atk))
    l_color2 = 'white' if low_index2 in [0, 1] else ('gold' if low_index2 in [2, 3] else 'purple')
    temp = p2_atk.copy()
    temp.remove(p2[low_index2])
    low2_index2 = p2.index(min(temp))
    l2_color2 = 'white' if low2_index2 in [0, 1] else ('gold' if low2_index2 in [2, 3] else 'purple')
    max_index2 = p2.index(max(p2_atk))
    m_color2 = 'white' if max_index2 in [0, 1] else ('gold' if max_index2 in [2, 3] else 'purple')
    try:
        l_val = min([i for i in p2[2:4] if i is not None])
        lg_index2 = [index for index, value in enumerate(p2) if value == l_val and index >= 2 and index < 4][0]
        g_val = max([i for i in p2[2:4] if i is not None])
        mg_index2 = [index for index, value in enumerate(p2) if value == g_val and index >= 2 and index < 4][0]
    except:
        lg_index2 = 2
        mg_index2 = 2
    m1 = ""
    index = None

    for effect in status_e[0]:
        effect = str(effect).lower()
        if 'next' in effect or 'knock' in effect or 'stars' in effect or '0 damage' in effect:
            continue
        match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
        val = float(match.group())

        if "increase" in effect:
            val = + val
            if "oppo" in effect:
                (index, m1) = (7, f'@op⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (None, '0')
                if index is None:
                    continue
                p2 = update_array(p2, index, val)

            else:
                (index, m1) = (7, f'@me⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@me⬆️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index1,
                      f'@me⬆️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                     ((max_index1,
                       f'@me⬆️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                      ((mg_index1,
                        f'@me⬆️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index1, f'@me⬆️{config.COLOR_MAPPING["gold"]}')))))
                # print(index, mg_index1, lg_index1)
                p1 = update_array(p1, index, val)

        elif "decrease" in effect:
            val = -val
            if "oppo" in effect:
                (index, m1) = (7, f'@op⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@op⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((mg_index2,
                      f'@op⬇️{config.COLOR_MAPPING["gold"]}') if ("highest" in effect and "gold" in effect) or (
                            "second lowest" in effect and "gold" in effect) else
                     ((low2_index2,
                       f'@op⬇️{config.COLOR_MAPPING[l2_color2]}') if "second lowest" in effect and "attack" in effect else
                      ((low_index2,
                        f'@op⬇️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                       ((max_index2,
                         f'@op⬇️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                        ((4 if (p2[4] is not None and p2[4] != 0) else (5 if p2[5] is not None else p2[4]),
                          f'@op⬇️{config.COLOR_MAPPING["purple"]}') if "purple" in effect else
                         (lg_index2, f'@op⬇️{config.COLOR_MAPPING["gold"]}')))))))
                p2 = update_array(p2, index, val)
            else:
                (index, m1) = (7, f'@me⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@me⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index1,
                      f'@me⬇️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                     ((max_index1,
                       f'@me⬇️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                      ((mg_index1,
                        f'@me⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index1, f'@me⬇️{config.COLOR_MAPPING["gold"]}')))))
                p1 = update_array(p1, index, val, own=True)
        print(m1)
        m1 += f" **{abs(val)}**%{index if index is not None else ''}"

    p1_atk = [i for i in p1[:4] if i is not None]
    low_index1 = p1.index(min(p1_atk))
    l_color1 = 'white' if low_index1 in [0, 1] else ('gold' if low_index1 in [2, 3] else 'purple')
    temp = p1_atk.copy()
    temp.remove(p1[low_index1])
    low2_index1 = p1.index(min(temp))
    l2_color1 = 'white' if low2_index1 in [0, 1] else ('gold' if low2_index1 in [2, 3] else 'purple')
    max_index1 = p1.index(max(p1_atk))
    m_color1 = 'white' if max_index1 in [0, 1] else ('gold' if max_index1 in [2, 3] else 'purple')
    try:
        l_val = min([i for i in p1[2:4] if i is not None])
        lg_index1 = [index for index, value in enumerate(p1) if value == l_val and index >= 2 and index < 4][0]
        g_val = max([i for i in p1[2:4] if i is not None])
        mg_index1 = [index for index, value in enumerate(p1) if value == g_val and index >= 2 and index < 4][0]
    except:
        lg_index1 = 2
        mg_index1 = 2

    p2_atk = [i for i in p2[:4] if i is not None]
    low_index2 = p2.index(min(p2_atk))
    l_color2 = 'white' if low_index2 in [0, 1] else ('gold' if low_index2 in [2, 3] else 'purple')
    max_index2 = p2.index(max(p2_atk))
    m_color2 = 'white' if max_index2 in [0, 1] else ('gold' if max_index2 in [2, 3] else 'purple')
    try:
        l_val = min([i for i in p2[2:4] if i is not None])
        lg_index2 = [index for index, value in enumerate(p2) if value == l_val and index >= 2 and index < 4][0]
        g_val = max([i for i in p2[2:4] if i is not None])
        mg_index2 = [index for index, value in enumerate(p2) if value == g_val and index >= 2 and index < 4][0]
    except:
        lg_index2 = 2
        mg_index2 = 2
    m2 = ""
    index = None

    for effect in status_e[1]:
        effect = str(effect).lower()
        if 'next' in effect or 'knock' in effect or 'stars' in effect or '0 damage' in effect:
            continue
        match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
        val = float(match.group())

        if "increase" in effect:
            val = + val
            if "oppo" in effect:
                (index, m2) = (7, f'@op⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (None, '0')
                if index is None:
                    continue
                p1 = update_array(p1, index, val)
            else:
                (index, m2) = (7, f'@me⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@me⬆️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index2,
                      f'@me⬆️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                     ((max_index2,
                       f'@me⬆️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                      ((mg_index2,
                        f'@me⬆️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index2, f'@me⬆️{config.COLOR_MAPPING["gold"]}')))))
                p2 = update_array(p2, index, val)

        elif "decrease" in effect:
            val = -val
            if "oppo" in effect:
                (index, m2) = (7, f'@op⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@op⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((mg_index1,
                      f'@op⬇️{config.COLOR_MAPPING["gold"]}') if ("highest" in effect and "gold" in effect) or (
                            "second lowest" in effect and "gold" in effect) else
                     ((low2_index1,
                       f'@op⬇️{config.COLOR_MAPPING[l2_color1]}') if "second lowest" in effect and "attack" in effect else
                      ((low_index1,
                        f'@op⬇️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                       ((max_index1,
                         f'@op⬇️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                        ((4 if (p1[4] is not None and p1[4] != 0) else (5 if p1[5] is not None else p1[4]),
                          f'@op⬇️{config.COLOR_MAPPING["purple"]}') if "purple" in effect else
                         (lg_index1, f'@op⬇️{config.COLOR_MAPPING["gold"]}')))))))
                p1 = update_array(p1, index, val)
            else:
                (index, m2) = (7, f'@me⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect or "miss" in effect else (
                    (6, f'@me⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index2,
                      f'@me⬇️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                     ((max_index2,
                       f'@me⬇️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                      ((mg_index2,
                        f'@me⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index2, f'@me⬇️{config.COLOR_MAPPING["gold"]}')))))
                p2 = update_array(p2, index, val, own=True)
        print(m2)
        m2 += f" **{abs(val)}**%{index if index is not None else ''}"

    print(f'new: {p1, p2} after {status_e}')
    print(m1, m2)
    return p1, p2, m1, m2

# print(apply_status_effects([21.0, 18.0, 21.0, 19.0, 11.0, None, None, 10.0], [10.0, None, 24.0, 15.0, 16.0, 16.0, 9.0, 10.0], [['Increases own highest percentage Gold by 10%'], []]))
