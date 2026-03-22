# frozen_string_literal: true

require_relative "shape"

# Utility module — showcases Enumerable pipelines, lazy enumerators, and refinements.
module Utils
  # Refinement that adds a convenience method to Numeric.
  module NumericExt
    refine Numeric do
      def degrees
        self * Math::PI / 180.0
      end
    end
  end

  module_function

  def total_area(shapes)
    shapes.sum(&:area)
  end

  def largest(shapes)
    shapes.max_by(&:area)
  end

  def filter_by(shapes, min_area: 0)
    shapes.lazy.select { |s| s.area >= min_area }
  end

  # Generates an infinite Fibonacci-like sequence of scaled shapes.
  def fibonacci_scales(shape)
    Enumerator.new do |yielder|
      a = 1
      b = 1
      loop do
        yielder.yield shape.scale(a)
        a, b = b, a + b
      end
    end.lazy
  end
end
