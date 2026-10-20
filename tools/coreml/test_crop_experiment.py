import unittest
from crop_experiment import crop_box, scan_boxes, restore_crop, merge_candidates, evaluate_labels
from vantage.records import Detection


class CropTests(unittest.TestCase):
    def test_edges_keep_crop_inside_native_image(self):
        self.assertEqual(crop_box((1900,1000),1920,1080,960),(960,120,1920,1080))
        self.assertEqual(crop_box((-100,-100),1920,1080,960),(0,0,960,960))

    def test_small_video_clamps_crop_size(self):
        self.assertEqual(crop_box((300,200),640,360,960),(120,0,480,360))

    def test_scan_has_no_gaps_and_covers_edges(self):
        boxes = scan_boxes(3840,2160,960)
        for y in range(0,2160,50):
            for x in range(0,3840,50):
                self.assertTrue(any(a<=x<c and b<=y<d for a,b,c,d in boxes))
        self.assertEqual(max(b[2] for b in boxes),3840)
        self.assertEqual(max(b[3] for b in boxes),2160)

    def test_crop_coordinates_are_restored_and_internal_edge_is_rejected(self):
        ds = [Detection((10,20,20,30),.8,None,32),Detection((0,20,10,30),.9,None,32)]
        out = restore_crop(ds,(100,100,1060,1060),1920,1080)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0].box,(110,120,120,130))

    def test_same_ball_is_not_counted_twice(self):
        a = Detection((10,10,20,20),.4,None,32)
        b = Detection((11,10,21,20),.8,None,32)
        self.assertEqual(merge_candidates([a],[b]),[b])

    def test_wrong_ball_counts_as_false_and_missed(self):
        record = dict(frame_index=3,baseline=None,cropped=dict(box=[100,100,110,110]))
        result = evaluate_labels([record],{'3':[20,20]},15)
        self.assertEqual(result['cropped']['missed'],1)
        self.assertEqual(result['cropped']['false_detection'],1)
        self.assertEqual(result['baseline']['false_detection'],0)


if __name__ == '__main__':
    unittest.main()
