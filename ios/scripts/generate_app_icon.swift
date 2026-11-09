// Run from the repository root: swift ios/scripts/generate_app_icon.swift
// The Vantage mark from site/index.html, on the app's dark brand background.
// Keep the square opaque; iOS applies its own corner mask.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size = 1024
let background = CGColor(red: 21 / 255.0, green: 27 / 255.0, blue: 34 / 255.0, alpha: 1)
let orange = CGColor(red: 232 / 255.0, green: 89 / 255.0, blue: 12 / 255.0, alpha: 1)
let context = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
    space: CGColorSpace(name: CGColorSpace.sRGB)!,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
context.setFillColor(background)
context.fill(CGRect(x: 0, y: 0, width: size, height: size))
context.translateBy(x: 132, y: 902)
context.scaleBy(x: 20, y: -20)
context.setFillColor(orange)
let mark = CGMutablePath()
mark.move(to: CGPoint(x: 2, y: 5))
mark.addLine(to: CGPoint(x: 12, y: 5))
mark.addLine(to: CGPoint(x: 19.2, y: 22.5))
mark.addLine(to: CGPoint(x: 26.3, y: 5))
mark.addLine(to: CGPoint(x: 36, y: 5))
mark.addLine(to: CGPoint(x: 23, y: 34))
mark.addLine(to: CGPoint(x: 15, y: 34))
mark.closeSubpath()
context.addPath(mark)
context.fillPath()
context.setStrokeColor(background)
context.setLineWidth(3)
context.move(to: CGPoint(x: 1, y: 18))
context.addLine(to: CGPoint(x: 33, y: 9))
context.strokePath()
let output = URL(fileURLWithPath: "ios/VantageMobile/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png")
try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, context.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Could not write app icon") }
print("Wrote \(output.path)")
