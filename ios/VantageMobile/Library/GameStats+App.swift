import VantageKit

extension GameStats {
    /// These stats when the analysis saw the ball at all, otherwise nil. With no ball evidence the
    /// pipeline still writes 0 rallies, 0 shots and 0 bounces, which mean "not measured", not "none".
    var measured: GameStats? { quality.status == .insufficientEvidence ? nil : self }
}
