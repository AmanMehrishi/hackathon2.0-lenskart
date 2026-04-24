import Foundation

// Copy-pasting core logic for standalone test script
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

class NGramClassifier {
    let config: IntentConfig
    let nValues = [1, 2, 3]
    init(config: IntentConfig) { self.config = config }
    func classify(_ text: String) -> IntentMatch {
        let inputTokens = tokenize(text)
        let inputNGrams = generateNGrams(from: inputTokens)
        var bestIntent = "unknown"
        var maxScore = 0.0
        for (intentName, detail) in config.intents {
            var intentMaxScore = 0.0
            for phrase in detail.phrases {
                let phraseTokens = tokenize(phrase)
                let phraseNGrams = generateNGrams(from: phraseTokens)
                let score = calculateOverlap(inputNGrams, phraseNGrams)
                if score > intentMaxScore { intentMaxScore = score }
            }
            if intentMaxScore > maxScore { maxScore = intentMaxScore; bestIntent = intentName }
        }
        let slots = extractSlots(from: text)
        let confidence = maxScore > 0 ? min(maxScore / 2.0, 1.0) : 0.0
        return IntentMatch(intent: bestIntent, confidence: confidence, slots: slots)
    }
    private func tokenize(_ text: String) -> [String] {
        return text.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }
    }
    private func generateNGrams(from tokens: [String]) -> Set<String> {
        var nGrams = Set<String>()
        for n in nValues {
            if tokens.count < n { continue }
            for i in 0...(tokens.count - n) {
                let gram = tokens[i..<(i+n)].joined(separator: " ")
                nGrams.insert(gram)
            }
        }
        return nGrams
    }
    private func calculateOverlap(_ setA: Set<String>, _ setB: Set<String>) -> Double {
        if setA.isEmpty || setB.isEmpty { return 0.0 }
        let intersection = setA.intersection(setB)
        return Double(intersection.count)
    }
    private func extractSlots(from text: String) -> [String: String] {
        var results = [String: String]()
        for (slotName, detail) in config.slots {
            if detail.method == "regex", let pattern = detail.pattern {
                if let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) {
                    let range = NSRange(text.startIndex..., in: text)
                    if let match = regex.firstMatch(in: text, options: [], range: range) {
                        if match.numberOfRanges > 1 {
                            let groupRange = match.range(at: 1)
                            if let swiftRange = Range(groupRange, in: text) {
                                results[slotName] = String(text[swiftRange]).uppercased()
                            }
                        } else {
                            if let swiftRange = Range(match.range, in: text) {
                                results[slotName] = String(text[swiftRange]).uppercased()
                            }
                        }
                    }
                }
            } else if detail.method == "value_list", let values = detail.values {
                for val in values {
                    let cleanVal = val.replacingOccurrences(of: "_", with: " ")
                    if text.lowercased().contains(cleanVal.lowercased()) {
                        results[slotName] = val
                        break
                    }
                }
            }
        }
        return results
    }
}

// Test Run
let jsonPath = "/Users/amanmehrishi/Documents/Hackathon2.0/voice-assistant-app/intents.json"
guard let data = try? Data(contentsOf: URL(fileURLWithPath: jsonPath)),
      let config = try? JSONDecoder().decode(IntentConfig.self, from: data) else {
    print("Error loading intents.json")
    exit(1)
}

let classifier = NGramClassifier(config: config)
let testPhrases = [
    "track my order ORD-123456",
    "where is my package?",
    "i want to cancel my order",
    "show me blue aviators",
    "recommend some glasses",
    "hi there",
    "speak to a human"
]

print("--- N-Gram Classifier Test ---")
for phrase in testPhrases {
    let result = classifier.classify(phrase)
    print("Input: '\(phrase)'")
    print("  Intent: \(result.intent)")
    print("  Confidence: \(result.confidence)")
    print("  Slots: \(result.slots)")
    print("------------------------------")
}
