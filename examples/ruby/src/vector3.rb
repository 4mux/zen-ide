# frozen_string_literal: true

# Immutable 3-component vector with operator overloading and Enumerable support.
class Vector3
  include Comparable
  include Enumerable

  attr_reader :x, :y, :z

  def initialize(x = 0.0, y = 0.0, z = 0.0)
    @x = x.to_f
    @y = y.to_f
    @z = z.to_f
    freeze
  end

  def each(&block)
    [@x, @y, @z].each(&block)
  end

  def +(other)
    self.class.new(@x + other.x, @y + other.y, @z + other.z)
  end

  def -(other)
    self.class.new(@x - other.x, @y - other.y, @z - other.z)
  end

  def *(scalar)
    self.class.new(@x * scalar, @y * scalar, @z * scalar)
  end

  def -@
    self * -1
  end

  def dot(other)
    @x * other.x + @y * other.y + @z * other.z
  end

  def cross(other)
    self.class.new(
      @y * other.z - @z * other.y,
      @z * other.x - @x * other.z,
      @x * other.y - @y * other.x
    )
  end

  def length
    Math.sqrt(dot(self))
  end

  def normalized
    len = length
    raise ZeroDivisionError, "cannot normalize zero vector" if len.zero?

    self * (1.0 / len)
  end

  def <=>(other)
    return nil unless other.is_a?(Vector3)

    length <=> other.length
  end

  def ==(other)
    other.is_a?(Vector3) && @x == other.x && @y == other.y && @z == other.z
  end

  def deconstruct
    [@x, @y, @z]
  end

  def deconstruct_keys(_keys)
    { x: @x, y: @y, z: @z }
  end

  def to_s
    format("Vector3(%.2f, %.2f, %.2f)", @x, @y, @z)
  end

  alias inspect to_s

  ZERO = new(0, 0, 0)
  UNIT_X = new(1, 0, 0)
  UNIT_Y = new(0, 1, 0)
  UNIT_Z = new(0, 0, 1)
end
