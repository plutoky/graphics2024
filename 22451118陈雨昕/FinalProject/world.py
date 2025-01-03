from chunk import Chunk
from constants import *
from numba.typed import Dict
import multiprocessing
import time
import glm
import numpy as np
from opensimplex.internals import _noise2, _noise3, _init
from OpenGL.GL import *
from world_gen import generate_terrain, getRandom
from chunk_builder import flatten_coord, to_uint8, is_empty, add_face, build_chunk

import random

def chunk_provider(chunkX, chunkZ, CHUNK_SIZE, CHUNK_HEIGHT, flatten_coord, to_uint8, is_empty, add_face, build_chunk, generate_terrain, seed, getRandom, blocks=[]):

    perm, perm_grad_index3 = _init(seed) # Variables used for Simplex noise

    # Generate block data for the current chunk
    blocks = generate_terrain(CHUNK_SIZE, CHUNK_HEIGHT, chunkX, chunkZ, flatten_coord, np.zeros(CHUNK_SIZE ** 2 * CHUNK_HEIGHT, dtype='uint8'), perm, perm_grad_index3, _noise2, _noise3, getRandom)        

    return chunkX, chunkZ, blocks, build_chunk(chunkX, 0, chunkZ, blocks) # Return block data and OpenGL vertex data
    
class World:
    def __init__(self, app):
        self.app = app
        self.chunks = {}
        self.pool = multiprocessing.Pool(processes=multiprocessing.cpu_count())
        self.needs_building = {}
        self.gen_queue = set() # Chunks that are already being generated in subprocesses
        self.firstLoad = False # Represents whether any chunk has been generated yet

        self.seed = random.randint(1, 10000) # Used for world generation

    def get_chunk(self, x, z):
        loc = (x, z)
        return self.chunks[loc] if loc in self.chunks else None

    def gen_chunk(self, x, z, blocks=[]):
        """
        Creates a new chunk object
        Can optionally pass in an array of blocks to avoid having to generate them.
        """
        self.chunks[(x, z)] = Chunk(self.app, position=[x*CHUNK_SIZE, 0, z*CHUNK_SIZE], blocks=blocks)

    def build_chunk(self, x, z, vertices=[]):
        """
        Generates and re-renders OpenGL vertices for chunks
        """
        if (x, z) in self.chunks:
            self.chunks[(x, z)].build(vertices)

    def get_block(self, x, y, z):
        """
        Returns a block based on an absolute (x, y, z) position
        """
        chunkX = x // CHUNK_SIZE
        chunkZ = z // CHUNK_SIZE
        if (chunkX, chunkZ) in self.chunks and y < 255:
            return self.chunks[(chunkX, chunkZ)].blocks[flatten_coord(x % CHUNK_SIZE, y, z % CHUNK_SIZE)]
        return False

    def render_chunks(self, position, isAsync=False):
        """
        Attempt to render every chunk within the render distance of the player's position. If it is not found, the chunk is generated.
        """
        chunk_pos = (int(position[0] // CHUNK_SIZE), int(position[2] // CHUNK_SIZE))
        for x in range(int(chunk_pos[0] - RENDER_DISTANCE), int(chunk_pos[0] + RENDER_DISTANCE + 1)):
            for z in range(int(chunk_pos[1] - RENDER_DISTANCE), int(chunk_pos[1] + RENDER_DISTANCE + 1)):
                if (x, z) not in self.chunks: # Chunk does not exist
                    if (x, z) in self.needs_building: 
                        # Chunk data has been generated asynchronously and now needs to be added to the world.
                        self.gen_chunk(x, z, self.needs_building[(x, z)][0])
                        self.build_chunk(x, z)
                        self.firstLoad = True
                        del self.needs_building[(x, z)]

                    elif (x, z) not in self.gen_queue:
                        # Chunk has not been generated yet and is not currently being generated
                        if isAsync:
                            # Pass on the generation function to the multiprocessing pool to generate chunk data asynchronously. 
                            self.gen_queue.add((x, z))

                            def call(result):
                                self.needs_building[(result[0], result[1])] = (result[2], result[3])
                                self.gen_queue.remove((result[0], result[1]))
                                
                            def error(err):
                                print(err)
                           
                            # Chunk is in loaded world
                            res = self.pool.apply_async(chunk_provider, (x, z, CHUNK_SIZE, CHUNK_HEIGHT, flatten_coord, to_uint8, is_empty, add_face, build_chunk, generate_terrain, self.seed, getRandom), callback=call, error_callback=error)
                        else:
                            # Directly generate chunk data
                            res = chunk_provider(x, z, CHUNK_SIZE, CHUNK_HEIGHT, flatten_coord, to_uint8, is_empty, add_face, build_chunk, generate_terrain, self.seed, getRandom)
                            self.needs_building[(res[0], res[1])] = (res[2], res[3])

                else: # Chunk exists and is in the world already
                    self.chunks[(x, z)].draw()