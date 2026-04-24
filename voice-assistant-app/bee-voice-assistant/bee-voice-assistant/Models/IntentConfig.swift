import Foundation

struct IntentDetail: Codable {
    let phrases: [String]
    let required_slots: [String]
    let escalate: Bool
}

struct SlotDetail: Codable {
    let method: String
    let pattern: String?
    let values: [String]?
}

struct IntentConfig: Codable {
    let intents: [String: IntentDetail]
    let slots: [String: SlotDetail]
}

struct IntentMatch: Codable {
    let intent: String
    let confidence: Double
    let slots: [String: String]
}
