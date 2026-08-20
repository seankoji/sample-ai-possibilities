"""Tests for the 18-Zone Spatial Module."""

from zones import get_zone_from_coords, clamp_coords_to_position_zones, ALLOWED_ZONES


def test_zone_detection():
    print("=== TEST 18-ZONE DETECTION ===")
    
    # Team 0 perspective (Attacks +x):
    # Left flank (y < -2.5): Zones 1, 4, 7, 10, 13, 16
    assert get_zone_from_coords(-45.0, -5.0, team_id=0) == 1
    assert get_zone_from_coords(-25.0, -5.0, team_id=0) == 4
    assert get_zone_from_coords(-10.0, -5.0, team_id=0) == 7
    assert get_zone_from_coords(10.0, -5.0, team_id=0) == 10
    assert get_zone_from_coords(25.0, -5.0, team_id=0) == 13
    assert get_zone_from_coords(45.0, -5.0, team_id=0) == 16
    print("  Left flank zones (1, 4, 7, 10, 13, 16) detected correctly")

    # Center lane (|y| <= 2.5): Zones 2, 5, 8, 11, 14, 17
    assert get_zone_from_coords(-45.0, 0.0, team_id=0) == 2
    assert get_zone_from_coords(-25.0, 0.0, team_id=0) == 5
    assert get_zone_from_coords(-10.0, 0.0, team_id=0) == 8
    assert get_zone_from_coords(10.0, 0.0, team_id=0) == 11
    assert get_zone_from_coords(25.0, 0.0, team_id=0) == 14
    assert get_zone_from_coords(45.0, 0.0, team_id=0) == 17
    print("  Center lane zones (2, 5, 8, 11, 14, 17) detected correctly")

    # Right flank (y > 2.5): Zones 3, 6, 9, 12, 15, 18
    assert get_zone_from_coords(-45.0, 5.0, team_id=0) == 3
    assert get_zone_from_coords(-25.0, 5.0, team_id=0) == 6
    assert get_zone_from_coords(-10.0, 5.0, team_id=0) == 9
    assert get_zone_from_coords(10.0, 5.0, team_id=0) == 12
    assert get_zone_from_coords(25.0, 5.0, team_id=0) == 15
    assert get_zone_from_coords(45.0, 5.0, team_id=0) == 18
    print("  Right flank zones (3, 6, 9, 12, 15, 18) detected correctly")


def test_position_zone_clamps():
    print("=== TEST POSITION ZONE CLAMPS ===")

    # 1. GK: Restricted to Zones 2, 5
    tx, ty = clamp_coords_to_position_zones(10.0, 15.0, "GK", 0, team_id=0)
    assert -52.0 <= tx <= -18.33
    assert abs(ty) <= 5.5
    assert get_zone_from_coords(tx, ty, team_id=0) in ALLOWED_ZONES["GK"]
    print("  GK clamped strictly to Zones 2, 5")

    # 2. DEF: Restricted to Zones 1, 4, 5, 6, 3, 8 (Defensive third + own half central)
    tx, ty = clamp_coords_to_position_zones(35.0, 15.0, "CB", 1, team_id=0)
    assert tx <= 0.0, "CB must not cross halfway line in normal play"
    assert get_zone_from_coords(tx, ty, team_id=0) in ALLOWED_ZONES["CB"]
    print("  DEF clamped strictly to Zones 1, 4, 5, 6, 3, 8")

    # 3. MID LEFT (LM): Restricted to Zones 4, 7, 10, 13, 16 (Left flank top lane)
    tx, ty = clamp_coords_to_position_zones(25.0, 10.0, "LM", 2, team_id=0)
    assert ty < 0.0, "LM must stay in left flank (negative y)"
    assert get_zone_from_coords(tx, ty, team_id=0) in ALLOWED_ZONES["LM"]
    print("  LM clamped strictly to Zones 4, 7, 10, 13, 16")

    # 4. MID RIGHT (RM): Restricted to Zones 6, 9, 12, 15, 18 (Right flank bottom lane)
    tx, ty = clamp_coords_to_position_zones(25.0, -10.0, "RM", 3, team_id=0)
    assert ty > 0.0, "RM must stay in right flank (positive y)"
    assert get_zone_from_coords(tx, ty, team_id=0) in ALLOWED_ZONES["RM"]
    print("  RM clamped strictly to Zones 6, 9, 12, 15, 18")

    # 5. STRIKER (ST): Restricted to Zones 11, 14, 17 (Opponent half central corridor, excluding 6-yd small box)
    tx, ty = clamp_coords_to_position_zones(52.0, 12.0, "ST", 4, team_id=0)
    assert tx <= 44.0, "ST capped at x=44 (out of 6-yard box)"
    assert tx >= 0.0, "ST operates in opponent half"
    assert abs(ty) <= 5.0, "ST operates in central corridor"
    assert get_zone_from_coords(tx, ty, team_id=0) in ALLOWED_ZONES["ST"]
    print("  ST clamped strictly to Zones 11, 14, 17 (excluding small 6-yd box)")


if __name__ == "__main__":
    test_zone_detection()
    test_position_zone_clamps()
    print("\n✅ All 18-Zone Spatial Tests PASSED.")
