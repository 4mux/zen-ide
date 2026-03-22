# frozen_string_literal: true

require_relative "shape"

# Axis-aligned rectangle — showcases keyword arguments and pattern matching.
class Rectangle < Shape
  register :rectangle

  attr_reader :width, :height

  def initialize(width, height, position: Vector3::ZERO)
    @width  = width.to_f
    @height = height.to_f
    super(position:)
  end

  def area
    @width * @height
  end

  def perimeter
    2 * (@width + @height)
  end

  def square?
    (@width - @height).abs < Float::EPSILON
  end

  def diagonal
    Math.sqrt(@width**2 + @height**2)
  end

  def scale(factor)
    self.class.new(@width * factor, @height * factor, position:)
  end

  def deconstruct_keys(_keys)
    { width: @width, height: @height, position: @position }
  end

  def to_s
    "Rectangle(#{format('%.2f', @width)}x#{format('%.2f', @height)})"
  end
end
