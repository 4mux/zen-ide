# frozen_string_literal: true

require_relative "shape"

# Collects shapes and renders a summary — showcases Enumerable, blocks, and Struct.
class Renderer
  include Enumerable

  Stats = Struct.new(:count, :total_area, :largest, keyword_init: true)

  def initialize
    @shapes = []
  end

  def <<(shape)
    @shapes << shape
    self
  end

  def each(&block)
    @shapes.each(&block)
  end

  def stats
    Stats.new(
      count: @shapes.size,
      total_area: @shapes.sum(&:area),
      largest: @shapes.max_by(&:area)
    )
  end

  def render
    puts "┌#{'─' * 40}┐"
    puts "│ Scene: #{@shapes.size} shapes#{' ' * (31 - @shapes.size.to_s.length)}│"
    puts "├#{'─' * 40}┤"

    @shapes.each_with_index do |shape, i|
      line = "  #{i + 1}. #{shape} — area #{format('%.2f', shape.area)}"
      puts "│ #{line.ljust(38)} │"
    end

    puts "├#{'─' * 40}┤"

    s = stats
    summary = "  Total area: #{format('%.2f', s.total_area)}"
    puts "│ #{summary.ljust(38)} │"
    puts "└#{'─' * 40}┘"
  end
end
