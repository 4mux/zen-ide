# frozen_string_literal: true

require_relative "vector3"

# Abstract base for 2-D shapes with a registry decorator.
class Shape
  @registry = {}

  class << self
    attr_reader :registry

    # Class-level decorator: registers a shape under a symbolic name.
    def register(name)
      Shape.registry[name] = self
    end
  end

  def initialize(position: Vector3::ZERO)
    raise NotImplementedError, "#{self.class} is abstract" if instance_of?(Shape)

    @position = position
  end

  attr_reader :position

  def area
    raise NotImplementedError
  end

  def perimeter
    raise NotImplementedError
  end

  def translate(offset)
    self.class.allocate.tap do |copy|
      instance_variables.each { |iv| copy.instance_variable_set(iv, instance_variable_get(iv)) }
      copy.instance_variable_set(:@position, @position + offset)
    end
  end

  def to_s
    "#{self.class.name}(area=#{format('%.2f', area)})"
  end

  alias inspect to_s
end
