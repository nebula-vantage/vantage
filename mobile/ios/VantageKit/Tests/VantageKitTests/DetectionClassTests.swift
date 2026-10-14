import XCTest
@testable import VantageKit

final class DetectionClassTests: XCTestCase {
    func testCOCONamesMapToCanonicalIDs() {
        let names = "{0: 'person', 1: 'bicycle', 32: 'sports ball', 37: 'surfboard', 38: 'tennis racket', 79: 'toothbrush'}"
        XCTAssertEqual(DetectionClass.canonicalMap(namesMetadata: names),
                       [0: DetectionClass.player, 32: DetectionClass.ball, 38: DetectionClass.paddle])
    }

    func testFineTunedNamesMapByName() {
        let names = "{0: 'player', 1: 'ball', 2: 'paddle'}"
        XCTAssertEqual(DetectionClass.canonicalMap(namesMetadata: names),
                       [0: DetectionClass.player, 1: DetectionClass.ball, 2: DetectionClass.paddle])
        XCTAssertEqual(DetectionClass.canonicalMap(namesMetadata: "{0: \"Pickleball\"}"), [0: DetectionClass.ball])
        XCTAssertEqual(DetectionClass.canonicalMap(namesMetadata: "{0: 'net'}"), [:])
    }
}
