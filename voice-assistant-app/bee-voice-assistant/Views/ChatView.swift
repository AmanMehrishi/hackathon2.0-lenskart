import SwiftUI

struct ChatView: View {
    @StateObject var viewModel = ChatViewModel()
    
    var body: some View {
        VStack {
            HStack {
                Image(systemName: "glasses")
                    .font(.largeTitle)
                Text("Lenskart Companion")
                    .font(.headline)
                Spacer()
                Circle()
                    .fill(viewModel.isRecording ? Color.red : Color.green)
                    .frame(width: 10, height: 10)
            }
            .padding()
            
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(viewModel.messages, id: \.self) { msg in
                        Text(msg)
                            .padding(10)
                            .background(msg.hasPrefix("User:") ? Color.blue.opacity(0.1) : Color.gray.opacity(0.1))
                            .cornerRadius(10)
                    }
                }
                .padding()
            }
            
            Spacer()
            
            if !viewModel.transcription.isEmpty {
                Text(viewModel.transcription)
                    .italic()
                    .foregroundColor(.gray)
                    .padding()
            }
            
            Button(action: {
                viewModel.toggleRecording()
            }) {
                Image(systemName: viewModel.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                    .resizable()
                    .frame(width: 80, height: 80)
                    .foregroundColor(viewModel.isRecording ? .red : .blue)
            }
            .padding(.bottom, 30)
        }
    }
}
