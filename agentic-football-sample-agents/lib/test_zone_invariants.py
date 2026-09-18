"""Regression checks for mirrored-team safety across the whole target grid."""
import unittest

from zones import clamp_coords_to_position_zones, get_zone_from_coords


class ZoneInvariants(unittest.TestCase):
    roles = (("GK", 0), ("CB", 1), ("LM", 2), ("RM", 3), ("ST", 4))
    targets = (-100, -55, -38, -19, -5, 0, 5, 19, 38, 55, 100)

    def test_team_one_mirrors_team_zero_in_both_normal_and_chasing_play(self):
        for role, player in self.roles:
            for chase in (False, True):
                for x in self.targets:
                    for y in (-30, -7, 0, 7, 30):
                        with self.subTest(role=role, chase=chase, x=x, y=y):
                            left = clamp_coords_to_position_zones(x, y, role, player, 0, chase)
                            right = clamp_coords_to_position_zones(-x, y, role, player, 1, chase)
                            self.assertEqual(right, (-left[0], left[1]))
                            self.assertEqual(get_zone_from_coords(*left, 0), get_zone_from_coords(*right, 1))

    def test_clamping_twice_never_drifts_a_target(self):
        for role, player in self.roles:
            for team in (0, 1):
                for x in self.targets:
                    for y in (-30, 0, 30):
                        first = clamp_coords_to_position_zones(x, y, role, player, team)
                        self.assertEqual(clamp_coords_to_position_zones(*first, role, player, team), first)

    def test_wingers_never_cross_flanks_for_either_team(self):
        for team in (0, 1):
            for x in self.targets:
                for y in (-100, 0, 100):
                    lm = clamp_coords_to_position_zones(x, y, "LM", 2, team)
                    rm = clamp_coords_to_position_zones(x, y, "RM", 3, team)
                    self.assertLess(lm[1], 0)
                    self.assertGreater(rm[1], 0)
                    self.assertLessEqual(abs(lm[1]), 7)
                    self.assertLessEqual(abs(rm[1]), 7)

    def test_defender_stays_out_of_own_goal_box_even_when_chasing(self):
        for team, own_goal in ((0, -55), (1, 55)):
            for chase in (False, True):
                x, _ = clamp_coords_to_position_zones(own_goal, 0, "CB", 1, team, chase)
                self.assertGreaterEqual(abs(x - own_goal), 17)

    def test_striker_stays_out_of_opponent_goal_box(self):
        for team, opponent_goal in ((0, 55), (1, -55)):
            for chase in (False, True):
                x, y = clamp_coords_to_position_zones(opponent_goal, 20, "ST", 4, team, chase)
                self.assertGreaterEqual(abs(x - opponent_goal), 11)
                self.assertLessEqual(abs(y), 5)


if __name__ == "__main__":
    unittest.main()
