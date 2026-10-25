import unittest
from compare import agreement


class AgreementTests(unittest.TestCase):
    def test_duplicate_candidates_cannot_match_reference_twice(self):
        detection = {"box": [0, 0, 10, 10], "class_id": 32, "confidence": 0.8}
        self.assertEqual(agreement([detection], [detection, detection])["matched"], 1)

    def test_same_box_wrong_class_is_not_a_match(self):
        detection = {"box": [0, 0, 10, 10], "class_id": 32, "confidence": 0.8}
        self.assertEqual(agreement([detection], [dict(detection, class_id=0)])["matched"], 0)

    def test_disjoint_boxes_are_not_matches(self):
        detection = {"box": [0, 0, 10, 10], "class_id": 32, "confidence": 0.8}
        self.assertEqual(agreement([detection], [dict(detection, box=[20,20,30,30])])["matched"], 0)


if __name__ == "__main__":
    unittest.main()
