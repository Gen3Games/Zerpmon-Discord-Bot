import config


def update_array(arr, index, value):

    if arr[index] is None:
        return arr
    # Distribute the value change among the other elements
    remaining_value = -value
    if value < 0 and abs(value) > arr[index]:
        remaining_value = arr[index]
    if value < 0 and arr[-1] is not None:
        arr[index] -= remaining_value
        arr[-1] += remaining_value
        return arr
    # if value > 0 and value
    _i = len([i for i in arr if i is not None]) - 1
    for i in range(len(arr)):
        if arr[i] is None:
            continue
        if i != index:
            delta = remaining_value / _i
            _i -= 1
            arr[i] += delta

            if arr[i] < 0:
                remaining_value += arr[i]
                arr[i] = 0
            remaining_value -= delta

    # Set the index value to the desired value
    arr[index] += value
    if arr[index] >= 100:
        return [0 if (i != index and i is not None) else (100 if i == index else arr[i]) for i in range(len(arr))]
    # Check if any values are out of bounds (i.e. negative or greater than 100)
    for i in range(len(arr)):
        if arr[i] is None:
            continue
        if arr[i] < 0:
            arr[i] = 0
        elif arr[i] > 100:
            arr[i] = 100

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
        val = int(effect[-3:-1])

        if "increases" in effect:
            val = + val
            if "opposing" in effect:
                (index, m1) = (7, f'op⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (None, '0')
                if index is None:
                    continue
                p2 = update_array(p2, index, val)

            else:
                (index, m1) = (7, f'me⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'me⬆️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index1, f'me⬆️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                     ((max_index1, f'me⬆️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                      ((mg_index1, f'me⬆️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index1, f'me⬆️{config.COLOR_MAPPING["gold"]}')))))
                # print(index, mg_index1, lg_index1)
                p1 = update_array(p1, index, val)

        elif "decreases" in effect:
            val = -val
            if "opposing" in effect:
                (index, m1) = (7, f'op⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'op⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index2, f'op⬇️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                     ((max_index2, f'op⬇️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                      ((mg_index2,
                        f'op⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index2, f'op⬇️{config.COLOR_MAPPING["gold"]}')))))
                p2 = update_array(p2, index, val)
            else:
                (index, m1) = (7, f'me⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'me⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index1,
                      f'me⬇️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                     ((max_index1,
                       f'me⬇️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                      ((mg_index1,
                        f'me⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index1, f'me⬇️{config.COLOR_MAPPING["gold"]}')))))
                p1 = update_array(p1, index, val)
        print(m1)
        m1 += f" **{abs(val)}**%{index if index is not None else ''}"

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
        val = int(effect[-3:-1])

        if "increases" in effect:
            val = + val
            if "opposing" in effect:
                (index, m2) = (7, f'op⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (None, '0')
                if index is None:
                    continue
                p1 = update_array(p1, index, val)
            else:
                (index, m2) = (7, f'me⬆️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'me⬆️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index2,
                      f'me⬆️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                     ((max_index2,
                       f'me⬆️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                      ((mg_index2,
                        f'me⬆️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index2, f'me⬆️{config.COLOR_MAPPING["gold"]}')))))
                p2 = update_array(p2, index, val)

        elif "decreases" in effect:
            val = -val
            if "opposing" in effect:
                (index, m2) = (7, f'op⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'op⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index1,
                      f'op⬇️{config.COLOR_MAPPING[l_color1]}') if "lowest" in effect and "attack" in effect else
                     ((max_index1,
                       f'op⬇️{config.COLOR_MAPPING[m_color1]}') if "highest" in effect and "attack" in effect else
                      ((mg_index1,
                        f'op⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index1, f'op⬇️{config.COLOR_MAPPING["gold"]}')))))
                p1 = update_array(p1, index, val)
            else:
                (index, m2) = (7, f'me⬇️{config.COLOR_MAPPING["miss"]}') if "red" in effect else (
                    (6, f'me⬇️{config.COLOR_MAPPING["blue"]}') if "blue" in effect else
                    ((low_index2,
                      f'me⬇️{config.COLOR_MAPPING[l_color2]}') if "lowest" in effect and "attack" in effect else
                     ((max_index2,
                       f'me⬇️{config.COLOR_MAPPING[m_color2]}') if "highest" in effect and "attack" in effect else
                      ((mg_index2,
                        f'me⬇️{config.COLOR_MAPPING["gold"]}') if "highest" in effect and "gold" in effect else
                       (lg_index2, f'me⬇️{config.COLOR_MAPPING["gold"]}')))))
                p2 = update_array(p2, index, val)
        print(m2)
        m2 += f" **{abs(val)}**%{index if index is not None else ''}"

    print(f'new: {p1, p2} after {status_e}')
    print(m1, m2)
    return p1, p2, m1, m2

# print(apply_status_effects([21.0, 18.0, 21.0, 19.0, 11.0, None, None, 10.0], [10.0, None, 24.0, 15.0, 16.0, 16.0, 9.0, 10.0], [['Increases own highest percentage Gold by 10%'], []]))