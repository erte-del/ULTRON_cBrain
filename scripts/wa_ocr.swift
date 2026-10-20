// Reads the text in a screenshot with macOS's own Vision framework (nothing leaves this Mac).
// usage: wa_ocr IMAGE.png   prints one line per text:  x0 y0 x1 y1<TAB>text   (0..1, origin top-left)
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1, let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { exit(2) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: cg).perform([request])
for o in request.results ?? [] {
    guard let text = o.topCandidates(1).first?.string else { continue }
    let b = o.boundingBox  // origin bottom-left
    print(String(format: "%.4f %.4f %.4f %.4f\t", b.minX, 1 - b.maxY, b.maxX, 1 - b.minY) + text.replacingOccurrences(of: "\n", with: " "))
}
