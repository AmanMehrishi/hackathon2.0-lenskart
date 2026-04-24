import Foundation
import Combine
import MLX
import MLXLMCommon
import MLXLLM
import MLXHuggingFace
import Tokenizers

class LLMManager: ObservableObject {
    @Published var isModelLoaded = false
    @Published var modelError: String?
    
    private var modelContainer: ModelContainer?
    private let generateParameters = GenerateParameters(maxTokens: 512, temperature: 0.2)
    
    func loadModel(at path: String) async {
        let url = URL(fileURLWithPath: path)
        print("Edge LLM: Loading model from \(path)...")
        
        do {
            // MLXLMCommon uses a free function when passing a specific tokenizer loader
            let container = try await loadModelContainer(
                from: url, 
                using: #huggingFaceTokenizerLoader()
            )
            
            await MainActor.run {
                self.modelContainer = container
                self.isModelLoaded = true
                print("Edge LLM: Model loaded successfully.")
            }
        } catch {
            await MainActor.run {
                self.modelError = "Failed to load: \(error.localizedDescription)"
                print("Edge LLM Error: \(error)")
            }
        }
    }
    
    func generateResponse(userText: String, history: [[String: String]], systemPrompt: String) async -> String {
        guard let container = modelContainer else {
            return "Error: Edge LLM is not loaded."
        }
        
        let prompt = formatPrompt(userText: userText, history: history, systemPrompt: systemPrompt)
        
        do {
            // Modern MLX-Swift uses instance methods directly on the container (no perform block needed)
            let input = try await container.prepare(input: MLXLMCommon.UserInput(prompt: prompt))
            let resultStream = try await container.generate(input: input, parameters: self.generateParameters)
            
            var fullText = ""
            for try await generation in resultStream {
                // The stream emits `Generation` enum events like .chunk, .toolCall, .info
                if let chunk = generation.chunk {
                    fullText += chunk
                }
            }
            return fullText
            
        } catch {
            return "Edge LLM Generation Error: \(error.localizedDescription)"
        }
    }
    
    private func formatPrompt(userText: String, history: [[String: String]], systemPrompt: String) -> String {
        var prompt = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n\(systemPrompt)<|eot_id|>"
        for turn in history.suffix(5) {
            let role = turn["role"] ?? "user"
            let content = turn["content"] ?? ""
            prompt += "<|start_header_id|>\(role)<|end_header_id|>\n\n\(content)<|eot_id|>"
        }
        prompt += "<|start_header_id|>user<|end_header_id|>\n\n\(userText)<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        return prompt
    }
}
