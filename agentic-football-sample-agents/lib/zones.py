"""
18-Zone Tactical Pitch Spatial Module
Implements the 18-zone pitch layout for 5v5 tactical positioning and strict zone boundaries.

Pitch is split into 18 zones:
- 6 Columns along length (Defensive Third: 1-2, Middle Third: 3-4, Final Third: 5-6)
- 3 Rows along width (Left Flank, Center Corridor, Right Flank)

Allowed zones per position:
- GK: 2, 5
- DEF: 1, 4, 5, 6, 3, 8 (and 2)
- MID LEFT (LM): 4, 7, 10, 13, 16
- MID RIGHT (RM): 6, 9, 12, 15, 18
- STRIKER (ST): 11, 14, 17 (only in the larger 18-yard box, NOT the small 6-yard goal box)
"""

from typing import Tuple, Set

# Allowed zones mapping
ALLOWED_ZONES = {
    "GK": {2, 5},
    "CB": {1, 2, 3, 4, 5, 6, 8},
    "DEF": {1, 2, 3, 4, 5, 6, 8},
    "LM": {4, 7, 10, 13, 16},
    "RM": {6, 9, 12, 15, 18},
    "ST": {11, 14, 17},
    "FWD": {11, 14, 17},
    "FWD1": {6, 9, 12, 15, 18},  # RM
    "FWD2": {11, 14, 17},         # ST
}


def get_zone_from_coords(x: float, y: float, team_id: int = 0) -> int:
    """
    Given (x, y) pitch coordinates and team_id (0=attacks +x, 1=attacks -x),
    returns the tactical zone number (1-18) from the team's perspective.
    """
    # Flip x if team 1 so that Column 1 is always own goal and Column 6 is opponent goal
    tx = x if team_id == 0 else -x
    
    # Determine column (1 to 6)
    # Pitch x is in [-55, 55] (110m total length, 6 bands of ~18.33m each)
    if tx <= -36.67:
        col = 0  # Column 1 (Zones 1, 2, 3)
    elif tx <= -18.33:
        col = 1  # Column 2 (Zones 4, 5, 6)
    elif tx <= 0.0:
        col = 2  # Column 3 (Zones 7, 8, 9)
    elif tx <= 18.33:
        col = 3  # Column 4 (Zones 10, 11, 12)
    elif tx <= 36.67:
        col = 4  # Column 5 (Zones 13, 14, 15)
    else:
        col = 5  # Column 6 (Zones 16, 17, 18)

    # Determine row (0=Left/Top, 1=Center, 2=Right/Bottom)
    if y <= -2.5:
        row = 0
    elif y >= 2.5:
        row = 2
    else:
        row = 1

    # Map (row, col) to Zone number
    # Top row: 1, 4, 7, 10, 13, 16
    # Center row: 2, 5, 8, 11, 14, 17
    # Bottom row: 3, 6, 9, 12, 15, 18
    zone_matrix = [
        [1, 4, 7, 10, 13, 16],
        [2, 5, 8, 11, 14, 17],
        [3, 6, 9, 12, 15, 18],
    ]
    return zone_matrix[row][col]


def clamp_coords_to_position_zones(
    target_x: float,
    target_y: float,
    position_label: str,
    my_player_id: int,
    team_id: int = 0,
    is_chasing: bool = False,
) -> Tuple[float, float]:
    """
    Enforces strict 18-zone boundaries and anti-wall safety cushions based on position.
    """
    label = (position_label or "").upper()
    tx = float(target_x)
    ty = float(target_y)

    # 1. GK: Allowed Zones 2, 5 (Central defensive corridor in defensive third: x in [-52, -19.0], |y| <= 2.0)
    if label == "GK" or my_player_id == 0:
        if team_id == 0:
            tx = max(-52.0, min(-19.0, tx))
        else:
            tx = min(52.0, max(19.0, tx))
        ty = max(-2.0, min(2.0, ty))
        return tx, ty

    # 2. DEF / CB: Allowed Zones 1, 4, 5, 6, 3, 8 (Defensive third + central own-half Zone 8)
    if label in ("CB", "DEF") or my_player_id == 1:
        if team_id == 0:
            max_x = 15.0 if is_chasing else 0.0
            tx = max(-52.0, min(max_x, tx))
            # In Zone 8 (between -19.0 and 0.0), restrict strictly to central corridor (|y| <= 2.0)
            if tx > -18.33:
                ty = max(-2.0, min(2.0, ty))
            else:
                ty = max(-7.0, min(7.0, ty))
        else:
            min_x = -15.0 if is_chasing else 0.0
            tx = max(min_x, min(52.0, tx))
            if tx < 18.33:
                ty = max(-2.0, min(2.0, ty))
            else:
                ty = max(-7.0, min(7.0, ty))
        return tx, ty

    # 3. MID LEFT (LM): Allowed Zones 4, 7, 10, 13, 16 (Left flank top lane: y in [-7.0, -3.0])
    if label == "LM" or my_player_id == 2:
        if team_id == 0:
            tx = max(-36.0, min(48.0, tx))
        else:
            tx = max(-48.0, min(36.0, tx))
        # Strictly left flank (top lane), anti-wall cushioned
        ty = max(-7.0, min(-3.0, ty))
        return tx, ty

    # 4. MID RIGHT (RM): Allowed Zones 6, 9, 12, 15, 18 (Right flank bottom lane: y in [3.0, 7.0])
    if label == "RM" or my_player_id == 3:
        if team_id == 0:
            tx = max(-36.0, min(48.0, tx))
        else:
            tx = max(-48.0, min(36.0, tx))
        # Strictly right flank (bottom lane), anti-wall cushioned
        ty = max(3.0, min(7.0, ty))
        return tx, ty

    # 5. STRIKER (ST): Allowed Zones 11, 14, 17 (Opponent half central corridor: x in [0.0, 48.5], |y| <= 2.0)
    # Special constraint: Allowed in larger 18-yard box, but NOT small 6-yard goal box (|tx| <= 48.5)
    if label in ("ST", "FWD", "FWD2") or my_player_id == 4:
        if team_id == 0:
            # Opponent half only (Zones 11, 14, 17): x in [0.0, 48.5]
            tx = max(0.0, min(48.5, tx))
        else:
            # Opponent half only: x in [-48.5, 0.0]
            tx = max(-48.5, min(0.0, tx))
        # Strictly central corridor
        ty = max(-2.0, min(2.0, ty))
        return tx, ty

    # Default fallback
    return max(-48.0, min(48.0, tx)), max(-6.5, min(6.5, ty))
