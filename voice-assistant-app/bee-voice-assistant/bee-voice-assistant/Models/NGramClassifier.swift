import Foundation

class NGramClassifier {
    private let config: IntentConfig
    private let nValues = [1, 2, 3]

    init(config: IntentConfig) {
        self.config = config
    }

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
                if score > intentMaxScore {
                    intentMaxScore = score
                }
            }
            
            if intentMaxScore > maxScore {
                maxScore = intentMaxScore
                bestIntent = intentName
            }
        }
        
        // Slot Extraction
        let slots = extractSlots(from: text)
        
        // Confidence is a simple heuristic: score / expected_score (cap at 1.0)
        // For now, we'll just use the raw score as a rough confidence if it meets a threshold
        let confidence = maxScore > 0 ? min(maxScore / 2.0, 1.0) : 0.0
        
        return IntentMatch(intent: bestIntent, confidence: confidence, slots: slots)
    }

    private func tokenize(_ text: String) -> [String] {
        return text.lowercased()
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
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
        // Weighted overlap: longer n-grams worth more? 
        // For simplicity, just count intersection size.
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
