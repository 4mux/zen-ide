# frozen_string_literal: true

require_relative "shape"

# Circle with radius — showcases Comparable, Struct-like freezing, lazy PI cache.
class Circle < Shape
  register :circle

  attr_reader :radius

  def initialize(radius, position: Vector3::ZERO)
    @radius = radius.to_f
    super(position:)
  end

  def area
    Math::PI * @radius**2
  end

  def perimeter
    2 * Math::PI * @radius
  end

  def scale(factor)
    self.class.new(@radius * factor, position:)
  end

  def <=>(other)
    return nil unless other.is_a?(Circle)

    @radius <=> other.radius
  end

  include Comparable

  def to_s
    "Circle(r=#{format('%.2f', @radius)})"
  end
end
