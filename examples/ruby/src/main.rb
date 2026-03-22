# frozen_string_literal: true

require_relative "circle"
require_relative "rectangle"
require_relative "renderer"
require_relative "utils"

using Utils::NumericExt

# — Build shapes ——————————————————————————————————————————
c1 = Circle.new(5)
c2 = Circle.new(3, position: Vector3.new(10, 0, 0))
r1 = Rectangle.new(4, 6)
r2 = Rectangle.new(5, 5, position: Vector3.new(0, 10, 0))

# — Registry lookup ———————————————————————————————————————
puts "Registered shapes: #{Shape.registry.keys.join(', ')}"

# — Pattern matching (Ruby 3.0+) ——————————————————————————
case r2.deconstruct_keys(nil)
in { width: w, height: ^w }
  puts "#{r2} is a square (#{w}x#{w})"
in { width: w, height: h }
  puts "#{r2} is #{w}x#{h}"
end

# — Comparable & sorting ——————————————————————————————————
shapes = [c1, c2, r1, r2]
puts "\nBy area: #{shapes.sort_by(&:area).map(&:to_s).join(', ')}"

# — Lazy Fibonacci scaling ————————————————————————————————
fibs = Utils.fibonacci_scales(Circle.new(1)).first(6)
puts "\nFibonacci circles: #{fibs.map { |c| format('r=%.0f', c.radius) }.join(', ')}"

# — Degrees refinement ————————————————————————————————————
puts "\n90° = #{90.degrees.round(4)} rad"

# — Render scene ——————————————————————————————————————————
renderer = Renderer.new
shapes.each { |s| renderer << s }
puts
renderer.render
