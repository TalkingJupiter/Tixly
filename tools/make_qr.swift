import AppKit
import CoreImage
import Foundation

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: make_qr.swift payload\n", stderr)
    exit(2)
}

let payload = CommandLine.arguments[1]
guard let message = payload.data(using: .utf8) else {
    fputs("Payload is not valid UTF-8\n", stderr)
    exit(1)
}

guard let filter = CIFilter(name: "CIQRCodeGenerator") else {
    fputs("Could not create QR filter\n", stderr)
    exit(1)
}

filter.setValue(message, forKey: "inputMessage")
filter.setValue("M", forKey: "inputCorrectionLevel")

guard let output = filter.outputImage else {
    fputs("Could not create QR image\n", stderr)
    exit(1)
}

let scaled = output.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
let context = CIContext()
guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else {
    fputs("Could not render QR image\n", stderr)
    exit(1)
}

let bitmap = NSBitmapImageRep(cgImage: cgImage)
guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Could not encode PNG\n", stderr)
    exit(1)
}

print(png.base64EncodedString())
