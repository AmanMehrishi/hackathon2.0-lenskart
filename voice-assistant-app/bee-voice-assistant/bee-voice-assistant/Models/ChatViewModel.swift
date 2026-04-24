import Foundation
import Combine

class ChatViewModel: ObservableObject {
    @Published var transcription = ""
    @Published var messages: [String] = []
    @Published var isRecording = false
    @Published var isModelLoaded = false
    @Published var statusMessage = "Initializing..."
    
    private let speechManager = SpeechManager()
    private let networkManager = NetworkManager()
    private var classifier: NGramClassifier?
    private var llmManager = LLMManager()
    private var toolOrchestrator: ToolOrchestrator?
    private var history: [[String: String]] = []
    private var cancellables = Set<AnyCancellable>()
    
    init() {
        setupEdgeIntelligence()
        
        speechManager.$transcribedText
            .assign(to: \.transcription, on: self)
            .store(in: &cancellables)
            
        speechManager.$isRecording
            .assign(to: \.isRecording, on: self)
            .store(in: &cancellables)
            
        llmManager.$isModelLoaded
            .assign(to: \.isModelLoaded, on: self)
            .store(in: &cancellables)
            
        networkManager.$messages
            .sink { [weak self] msgs in
                if let last = msgs.last {
                    self?.messages.append(last)
                    self?.speechManager.speak(last)
                }
            }
            .store(in: &cancellables)
            
        networkManager.connect(sessionID: "swift_session_\(Int.random(in: 1000...9999))")
    }
    
    private func setupEdgeIntelligence() {
        // 1. Classifier
        if let path = Bundle.main.path(forResource: "intents", ofType: "json"),
           let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
           let config = try? JSONDecoder().decode(IntentConfig.self, from: data) {
            self.classifier = NGramClassifier(config: config)
        }
        
        // 2. Real Edge LLM
        Task {
            var modelPath = Bundle.main.path(forResource: "Llama-3.2-3B-Instruct-4bit", ofType: nil)
            if modelPath == nil {
                modelPath = "/Users/amanmehrishi/Documents/Hackathon2.0/voice-assistant-app/bee-voice-assistant/bee-voice-assistant/Llama-3.2-3B-Instruct-4bit"
            }
            
            if let path = modelPath {
                await MainActor.run { self.statusMessage = "Loading Llama 3.2 (4-bit)..." }
                await llmManager.loadModel(at: path)
                await MainActor.run { self.statusMessage = llmManager.isModelLoaded ? "Stable" : "Model Error" }
            }
            
            // 3. Orchestrator
            await MainActor.run {
                self.toolOrchestrator = ToolOrchestrator(llmManager: llmManager, networkManager: networkManager)
            }
        }
    }
    
    func toggleRecording() {
        if isRecording {
            speechManager.stopRecording()
            Task {
                await processText(transcription)
            }
        } else {
            transcription = ""
            speechManager.startRecording()
        }
    }
    
    private func processText(_ text: String) async {
        guard !text.isEmpty else { return }
        
        await MainActor.run {
            messages.append("User: \(text)")
            history.append(["role": "user", "content": text])
        }
        
        if let classifier = classifier, let orchestrator = toolOrchestrator {
            let match = classifier.classify(text)
            print("Edge Intent: \(match.intent) (Confidence: \(match.confidence))")
            
            // Tier 0 -> Tier 2 Escalation: If intent confidence is bad, escalate intent + tool calling to Gemini
            if match.intent == "unknown" || match.confidence <= 0.0 {
                print("Tier 0: Low confidence intent. Escalating to Gemini (Tier 2)...")
                networkManager.send(text: text) // No intent payload means backend will run it from scratch and escalate
            } else {
                // High confidence intent -> Proceed to Tier 1 local LLM
                let response = await orchestrator.processTurn(text: text, intent: match.intent, slots: match.slots, history: history)
                
                await MainActor.run {
                    if !response.isEmpty && response != "Executing request..." && response != "This seems complex! Let me grab that from the cloud..." {
                        messages.append("Assistant (Local): \(response)")
                        history.append(["role": "assistant", "content": response])
                        speechManager.speak(response)
                    } else if response.contains("cloud") {
                        messages.append("System: Escalating to Gemini...")
                    }
                }
            }
        } else {
            networkManager.send(text: text)
        }
    }
}
